/**
 * Fetch an http(s) URL and report its title and body word count.
 *
 * Framework-free. Nothing in this module knows what OpenClaw is; everything
 * that does lives in index.ts. Failures are thrown as PageStatsError so the
 * contract layer decides how an agent sees them.
 *
 * The algorithm is fixed by spec/page-stats.md. langchain/src/dialects_page_stats/core.py
 * is the same algorithm in Python and must produce identical numbers on
 * identical bytes.
 */

export const DEFAULT_USER_AGENT = "dialects-page-stats/1.0";
export const DEFAULT_MAX_BYTES = 2_000_000;
export const DEFAULT_TIMEOUT_SECONDS = 10;
export const MIN_TIMEOUT_SECONDS = 1;
export const MAX_TIMEOUT_SECONDS = 60;

const HTML_CONTENT_TYPES = ["text/html", "application/xhtml+xml"];

const TITLE = /<title\b[^>]*>([\s\S]*?)(?:<\/title\s*>|$)/i;
const DROPPED = /<(script|style|title)\b[^>]*>[\s\S]*?(?:<\/\1\s*>|$)/gi;
const TAG = /<[^>]*>/g;
const NUMERIC_ENTITY = /&#(x[0-9a-fA-F]+|[0-9]+);/g;
const NAMED_ENTITIES: Record<string, string> = {
  "&amp;": "&",
  "&lt;": "<",
  "&gt;": ">",
  "&quot;": '"',
  "&#39;": "'",
  "&nbsp;": " ",
};

export type PageStatsPayload = {
  ok: true;
  url: string;
  final_url: string;
  status: number;
  content_type: string;
  title: string | null;
  word_count: number;
  truncated: boolean;
};

export type PageStatsErrorPayload = {
  ok: false;
  error_code: string;
  message: string;
  [key: string]: unknown;
};

/** A failure that carries a machine-readable code alongside its message. */
export class PageStatsError extends Error {
  readonly errorCode: string;
  readonly extra: Record<string, unknown>;

  constructor(errorCode: string, message: string, extra: Record<string, unknown> = {}) {
    super(message);
    this.name = "PageStatsError";
    this.errorCode = errorCode;
    this.extra = extra;
  }

  toPayload(): PageStatsErrorPayload {
    return { ok: false, error_code: this.errorCode, message: this.message, ...this.extra };
  }
}

function decodeEntities(text: string): string {
  let decoded = text;
  for (const [entity, char] of Object.entries(NAMED_ENTITIES)) {
    decoded = decoded.split(entity).join(char);
  }
  return decoded.replace(NUMERIC_ENTITY, (match, raw: string) => {
    const code = raw[0] === "x" || raw[0] === "X" ? parseInt(raw.slice(1), 16) : parseInt(raw, 10);
    try {
      return String.fromCodePoint(code);
    } catch {
      return match;
    }
  });
}

function countWords(text: string): number {
  const trimmed = text.trim();
  return trimmed ? trimmed.split(/\s+/u).length : 0;
}

/** Apply the fixed parse of spec/page-stats.md. */
export function parseHtml(html: string): { title: string | null; wordCount: number } {
  const match = TITLE.exec(html);
  let title: string | null = null;
  if (match) {
    const candidate = decodeEntities(match[1].replace(TAG, "")).trim().replace(/\s+/gu, " ");
    title = candidate || null;
  }

  const body = decodeEntities(html.replace(DROPPED, " ").replace(TAG, " "));
  return { title, wordCount: countWords(body) };
}

/**
 * Check timeout_seconds the way the spec's table says.
 *
 * A framework whose schema layer enforces the bound never reaches the throw.
 */
export function validateTimeout(value: unknown): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new PageStatsError(
      "invalid_parameter",
      `timeout_seconds must be a number, got ${typeof value}.`,
    );
  }
  if (!Number.isInteger(value)) {
    throw new PageStatsError(
      "invalid_parameter",
      `timeout_seconds must be a whole number of seconds, got ${value}.`,
    );
  }
  if (value < MIN_TIMEOUT_SECONDS || value > MAX_TIMEOUT_SECONDS) {
    throw new PageStatsError(
      "invalid_parameter",
      `timeout_seconds must be between ${MIN_TIMEOUT_SECONDS} and ${MAX_TIMEOUT_SECONDS}, got ${value}.`,
    );
  }
  return value;
}

function isHtml(contentType: string): boolean {
  return HTML_CONTENT_TYPES.includes(contentType.split(";")[0].trim().toLowerCase());
}

async function readBody(
  response: Response,
  maxBytes: number,
): Promise<{ bytes: Uint8Array; truncated: boolean }> {
  if (!response.body) {
    return { bytes: new Uint8Array(0), truncated: false };
  }

  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  try {
    while (total <= maxBytes) {
      const { done, value } = await reader.read();
      if (done) break;
      chunks.push(value);
      total += value.length;
    }
  } finally {
    await reader.cancel().catch(() => {});
  }

  const merged = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    merged.set(chunk, offset);
    offset += chunk.length;
  }
  return { bytes: merged.subarray(0, maxBytes), truncated: total > maxBytes };
}

export type FetchOptions = {
  timeoutSeconds?: number;
  userAgent?: string;
  maxBytes?: number;
  signal?: AbortSignal;
};

/**
 * Fetch url and return the success payload of spec/page-stats.md.
 *
 * Throws PageStatsError on every failure the spec names. An abort on the
 * caller's signal is re-thrown as-is, because a cancelled call has no result.
 */
export async function fetchPageStats(
  url: unknown,
  options: FetchOptions = {},
): Promise<PageStatsPayload> {
  const {
    timeoutSeconds = DEFAULT_TIMEOUT_SECONDS,
    userAgent = DEFAULT_USER_AGENT,
    maxBytes = DEFAULT_MAX_BYTES,
    signal,
  } = options;

  if (typeof url !== "string") {
    throw new PageStatsError("invalid_url", `url must be a string, got ${typeof url}.`);
  }

  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    throw new PageStatsError("invalid_url", `Not an absolute http(s) URL: ${JSON.stringify(url)}.`);
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    throw new PageStatsError("invalid_url", `Not an absolute http(s) URL: ${JSON.stringify(url)}.`);
  }

  const seconds = validateTimeout(timeoutSeconds);
  const timeoutSignal = AbortSignal.timeout(seconds * 1000);
  const composite = signal ? AbortSignal.any([signal, timeoutSignal]) : timeoutSignal;

  const fail = (error: unknown): never => {
    if (signal?.aborted) throw error;
    if (timeoutSignal.aborted) {
      throw new PageStatsError("timeout", `No response within ${seconds}s.`);
    }
    throw new PageStatsError(
      "unreachable",
      `Could not reach ${url}: ${error instanceof Error ? error.message : String(error)}.`,
    );
  };

  let response: Response;
  try {
    response = await fetch(url, {
      headers: { "User-Agent": userAgent },
      redirect: "follow",
      signal: composite,
    });
  } catch (error) {
    return fail(error);
  }

  if (!response.ok) {
    await response.body?.cancel().catch(() => {});
    throw new PageStatsError("http_error", `Server returned ${response.status}.`, {
      status: response.status,
    });
  }

  const contentType = response.headers.get("content-type") ?? "";
  if (!isHtml(contentType)) {
    await response.body?.cancel().catch(() => {});
    throw new PageStatsError(
      "unsupported_content_type",
      `Expected HTML, got ${contentType || "no Content-Type"}.`,
      { content_type: contentType },
    );
  }

  let body: { bytes: Uint8Array; truncated: boolean };
  try {
    body = await readBody(response, maxBytes);
  } catch (error) {
    return fail(error);
  }

  const { title, wordCount } = parseHtml(new TextDecoder("utf-8").decode(body.bytes));
  return {
    ok: true,
    url,
    final_url: response.url,
    status: response.status,
    content_type: contentType,
    title,
    word_count: wordCount,
    truncated: body.truncated,
  };
}

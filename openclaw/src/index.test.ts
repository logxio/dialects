/**
 * What OpenClaw's contract actually does, run against a local fixture server.
 *
 * The tool is driven through the same api.registerTool descriptor the Gateway
 * builds, and the argument tests call validateToolArguments, which is the exact
 * function OpenClaw's agent loop runs on every model-emitted tool call.
 */

import { readFileSync } from "node:fs";
import { createServer } from "node:http";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { validateToolArguments } from "openclaw/plugin-sdk/agent-core";
import { getToolPluginMetadata } from "openclaw/plugin-sdk/tool-plugin";

import entry from "./index.js";
import { startFixtureServer } from "../../fixtures/server.mjs";

const ARTICLE_WORDS = 37;
const ARTICLE_TITLE = "Tide Tables & Other Regularities";

type RegisteredTool = {
  name: string;
  parameters: unknown;
  execute: (
    toolCallId: string,
    params: Record<string, unknown>,
    signal?: AbortSignal,
  ) => Promise<{ content: Array<{ type: string; text: string }>; details?: unknown }>;
};

/** Collects what the plugin registers, the way the Gateway would. */
function registerTools(pluginConfig: Record<string, unknown> = {}): RegisteredTool[] {
  const tools: RegisteredTool[] = [];
  entry.register({
    pluginConfig,
    registerTool: (tool: unknown) => tools.push(tool as RegisteredTool),
  } as never);
  return tools;
}

const pageStats = (pluginConfig: Record<string, unknown> = {}) => {
  const tool = registerTools(pluginConfig).find((t) => t.name === "page_stats");
  if (!tool) throw new Error("page_stats was not registered");
  return tool;
};

const details = async (params: Record<string, unknown>, pluginConfig = {}) =>
  (await pageStats(pluginConfig).execute("call_1", params)).details as Record<string, unknown>;

async function failure(params: Record<string, unknown>): Promise<Record<string, unknown>> {
  try {
    await pageStats().execute("call_1", params);
  } catch (error) {
    return JSON.parse((error as Error).message);
  }
  throw new Error("expected the tool to throw");
}

async function closedPort(): Promise<number> {
  const server = createServer();
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", () => resolve()));
  const { port } = server.address() as { port: number };
  await new Promise<void>((resolve) => server.close(() => resolve()));
  return port;
}

let fixture: Awaited<ReturnType<typeof startFixtureServer>>;
let baseUrl: string;

beforeAll(async () => {
  fixture = await startFixtureServer();
  baseUrl = fixture.baseUrl;
});

afterAll(async () => {
  await fixture.close();
});

describe("metadata", () => {
  it("declares one tool, statically, without running plugin code", () => {
    const metadata = getToolPluginMetadata(entry);

    expect(metadata?.tools.map((tool) => tool.name)).toEqual(["page_stats"]);
  });

  it("matches the generated manifest the Gateway reads for discovery", () => {
    const manifest = JSON.parse(
      readFileSync(new URL("../openclaw.plugin.json", import.meta.url), "utf8"),
    );

    expect(manifest.contracts.tools).toEqual(["page_stats"]);
    expect(manifest.id).toBe(getToolPluginMetadata(entry)?.id);
  });
});

describe("results", () => {
  it("returns a structured value, and the model sees it as JSON text", async () => {
    const result = await pageStats().execute("call_1", { url: `${baseUrl}/article` });

    expect(result.details).toMatchObject({
      ok: true,
      title: ARTICLE_TITLE,
      word_count: ARTICLE_WORDS,
      status: 200,
      truncated: false,
    });
    expect(JSON.parse(result.content[0].text)).toEqual(result.details);
  });

  it("reports the redirect target in final_url", async () => {
    const result = await details({ url: `${baseUrl}/redirect` });

    expect(result.url).toBe(`${baseUrl}/redirect`);
    expect(result.final_url).toBe(`${baseUrl}/article`);
  });

  it("reports a missing title as null", async () => {
    expect(await details({ url: `${baseUrl}/no-title` })).toMatchObject({
      title: null,
      word_count: 4,
    });
  });

  it("takes maxBytes from plugin config and truncates", async () => {
    const result = await details({ url: `${baseUrl}/article` }, { maxBytes: 200 });

    expect(result.truncated).toBe(true);
    expect(result.word_count).toBeLessThan(ARTICLE_WORDS);
  });
});

describe("failures", () => {
  it.each([
    ["/not-found", "http_error"],
    ["/binary", "unsupported_content_type"],
  ])("throws for %s", async (path, errorCode) => {
    expect(await failure({ url: `${baseUrl}${path}` })).toMatchObject({
      ok: false,
      error_code: errorCode,
    });
  });

  it("throws on timeout", async () => {
    const result = await failure({ url: `${baseUrl}/slow?ms=3000`, timeout_seconds: 1 });

    expect(result.error_code).toBe("timeout");
  });

  it("throws when the host refuses the connection", async () => {
    const result = await failure({ url: `http://127.0.0.1:${await closedPort()}/article` });

    expect(result.error_code).toBe("unreachable");
  });

  it("throws for a URL that is not http or https", async () => {
    expect(await failure({ url: "not-a-url" })).toMatchObject({ error_code: "invalid_url" });
  });
});

describe("cancellation", () => {
  it("propagates an abort instead of turning it into a result", async () => {
    const controller = new AbortController();
    const running = pageStats().execute(
      "call_1",
      { url: `${baseUrl}/slow?ms=3000` },
      controller.signal,
    );
    setTimeout(() => controller.abort(), 50);

    const error = await running.then(
      () => new Error("expected the tool to reject"),
      (reason: unknown) => reason as Error,
    );

    expect(error.name).toBe("AbortError");
    expect(error.message).not.toContain("error_code");
  });

  it("refuses to start when the signal is already aborted", async () => {
    await expect(
      pageStats().execute("call_1", { url: `${baseUrl}/article` }, AbortSignal.abort()),
    ).rejects.toThrow();
  });
});

describe("argument validation, by OpenClaw's own validator", () => {
  const validate = (args: Record<string, unknown>) =>
    validateToolArguments(pageStats() as never, { name: "page_stats", arguments: args } as never);

  it("rejects a missing required parameter", () => {
    expect(() => validate({})).toThrow(/url/);
  });

  it("rejects a timeout above the declared maximum", () => {
    expect(() => validate({ url: "http://example.test", timeout_seconds: 999 })).toThrow(
      /timeout_seconds/,
    );
  });

  it("coerces a numeric string to an integer", () => {
    expect(validate({ url: "http://example.test", timeout_seconds: "30" })).toEqual({
      url: "http://example.test",
      timeout_seconds: 30,
    });
  });

  it("rejects a string that is not a number", () => {
    expect(() => validate({ url: "http://example.test", timeout_seconds: "soon" })).toThrow(
      /timeout_seconds/,
    );
  });

  it("does not inject the schema default", () => {
    expect(validate({ url: "http://example.test" })).toEqual({ url: "http://example.test" });
  });
});

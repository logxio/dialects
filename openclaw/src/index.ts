/**
 * The OpenClaw contract surface for page_stats.
 *
 * Everything here is OpenClaw: a TypeBox parameter schema, a TypeBox config
 * schema, and a throw as the failure channel. The fetching lives in core.ts.
 *
 * openclaw.plugin.json is generated from this file by `openclaw plugins build`
 * and is what the Gateway reads to discover the tool without importing any of
 * this code.
 */

import { Type } from "typebox";
import { defineToolPlugin } from "openclaw/plugin-sdk/tool-plugin";

import {
  DEFAULT_MAX_BYTES,
  DEFAULT_TIMEOUT_SECONDS,
  DEFAULT_USER_AGENT,
  MAX_TIMEOUT_SECONDS,
  MIN_TIMEOUT_SECONDS,
  PageStatsError,
  fetchPageStats,
} from "./core.js";

export default defineToolPlugin({
  id: "page-stats",
  name: "Page Stats",
  description: "Read a web page and report its title and word count.",

  // Set once in the Gateway config, under this plugin's entry. The model never
  // sees it and cannot change it per call.
  configSchema: Type.Object({
    userAgent: Type.Optional(
      Type.String({ description: "Sent as the User-Agent header on every request." }),
    ),
    maxBytes: Type.Optional(
      Type.Integer({
        minimum: 1,
        description: "Stop reading the response body after this many bytes.",
      }),
    ),
  }),

  tools: (tool) => [
    tool({
      name: "page_stats",
      label: "Page Stats",
      description:
        "Fetch a web page over http or https and report its title and the number of " +
        "words in its body. Use it to check what a URL actually contains before " +
        "deciding whether to read the whole thing.",
      parameters: Type.Object({
        url: Type.String({ description: "Absolute http or https URL of the page to read." }),
        timeout_seconds: Type.Optional(
          Type.Integer({
            minimum: MIN_TIMEOUT_SECONDS,
            maximum: MAX_TIMEOUT_SECONDS,
            default: DEFAULT_TIMEOUT_SECONDS,
            description: "How long to wait for the response, in seconds.",
          }),
        ),
      }),

      async execute(params, config, context) {
        context.signal?.throwIfAborted();

        try {
          return await fetchPageStats(params.url, {
            // The schema's default is advisory to the model; the runtime does
            // not inject it, so the fallback has to be here.
            timeoutSeconds: params.timeout_seconds ?? DEFAULT_TIMEOUT_SECONDS,
            userAgent: config.userAgent ?? DEFAULT_USER_AGENT,
            maxBytes: config.maxBytes ?? DEFAULT_MAX_BYTES,
            signal: context.signal,
          });
        } catch (error) {
          if (error instanceof PageStatsError) {
            // The agent loop catches this and hands the model the message text
            // as a tool result flagged isError.
            throw new Error(JSON.stringify(error.toPayload()));
          }
          throw error;
        }
      },
    }),
  ],
});

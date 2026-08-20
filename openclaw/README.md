# page_stats for OpenClaw

An OpenClaw tool plugin that fetches an http or https URL and reports the page
title and body word count. The contract it implements is
[../spec/page-stats.md](../spec/page-stats.md).

Requires Node 22.22.3+, 24.15+, or 25.9+, which is what the OpenClaw CLI
enforces. Tested against openclaw 2026.7.1-2 and typebox 1.x on Node 24.19.0.

## Build

```bash
pnpm install
pnpm run plugin:build
pnpm run plugin:validate
```

`plugin:build` compiles TypeScript, then runs `openclaw plugins build`, which
regenerates `openclaw.plugin.json` from the entry's static metadata and aligns
`package.json`. `plugin:validate` re-checks that the manifest, the entry, and
`contracts.tools` still agree. Rerun both after changing the plugin id, name,
description, config schema, or any tool name.

## Install

```bash
openclaw plugins install .
openclaw plugins inspect page-stats --runtime
```

Restart or reload the Gateway afterwards.

## Configure

`userAgent` and `maxBytes` live under this plugin's entry in the Gateway config,
typed by the `configSchema` in `src/index.ts`. The model never sees them.

## Files

| File | Lines | What it is |
| --- | ---: | --- |
| `src/index.ts` | 87 | The entire OpenClaw contract: config schema, parameter schema, execute |
| `src/core.ts` | 263 | Fetching and parsing, framework-free |
| `openclaw.plugin.json` | 28 | Generated, not hand-written |
| `src/index.test.ts` | 216 | Every claim the root README makes about OpenClaw |

`src/core.ts` is the TypeScript port of
`langchain/src/dialects_page_stats/core.py`. `scripts/parity.py` and
`scripts/parity.mjs` assert the two produce identical output on identical bytes.

## Tests

```bash
pnpm test
```

The tool is driven through the same `api.registerTool` descriptor the Gateway
builds, against a local fixture server from `../fixtures/`. The argument tests
call `validateToolArguments` from `openclaw/plugin-sdk/agent-core`, which is the
function OpenClaw's agent loop runs on every model-emitted tool call.

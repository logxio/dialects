# Status

Terminal state of this repository. Rewritten in place, never appended to.

## The example tool

`page_stats` fetches an http or https URL and reports the page title and body
word count.

Selection criteria and how it meets them:

| Requirement | How |
| --- | --- |
| No private service | Fetches any public URL; tests run against a local fixture server in `fixtures/` |
| No API key | None used anywhere |
| Runs after installing dependencies | `langchain-core` for one, `dify_plugin` for one, `typebox` for one; fetching and parsing use only the standard library and Node built-ins |
| Exercises input schema validation | `timeout_seconds` is an integer bounded 1..60, declared in all three schema languages |
| Exercises result and error returns | Six named error codes plus a structured success payload |
| Exercises timeout | `timeout_seconds` is a real request deadline; `/slow` fixture route triggers it |
| Exercises configuration | `user_agent` and `max_bytes` come from each ecosystem's configuration channel |

The contract is pinned in `spec/page-stats.md`, down to the HTML entity table,
so the three implementations produce identical numbers on identical bytes and
any difference between them is a contract difference.

## Verification

Everything below was run on macOS 15 (Darwin 25.5.0, arm64). One command
reproduces it:

```bash
./scripts/verify.sh
```

### LangChain

```
$ .venv-langchain/bin/python -m pytest langchain/tests -q
18 passed in 1.61s
```

langchain-core 1.6.0, pydantic 2.13.4, CPython 3.13.14. Tests cover the success
payload, redirects, missing title, truncation via `max_bytes`, all six error
codes, `ToolException` propagation, `handle_tool_error=True` producing a
`ToolMessage` with `status="error"`, pydantic coercion and bound enforcement,
default filling, `ainvoke` working with only `_run` defined, and the OpenAI tool
schema the model receives.

### Dify

```
$ .venv-dify/bin/python -m pytest dify/tests -q
17 passed, 2 warnings in 1.82s

$ dify-plugin plugin package ./dify -o /tmp/page-stats.difypkg
INFO plugin packaged successfully

$ dify-plugin plugin checksum /tmp/page-stats.difypkg
INFO plugin checksum checksum=9153e39804d2b773f6ef19b1e1930396ef7f9f07a0bff7709dc335736c514576
```

dify_plugin 0.10.2, Dify CLI 0.6.10, CPython 3.13.14. The manifest tests
validate `manifest.yaml`, `provider/page_stats.yaml`, and `tools/page_stats.yaml`
against `PluginConfiguration` and `ToolProviderConfiguration`, the pydantic
models that ship in `dify_plugin` and that the plugin daemon loads them with.
The runtime tests load the tool and provider classes through the SDK's own
`load_single_subclass_from_source`, by path, from `extra.python.source`, then
drive them through `Tool.from_credentials(...).invoke(...)`.

Two packaging behaviours were established by deliberately breaking a copy:

```
# provider yaml pointing at a tool yaml that does not exist
$ dify-plugin plugin package ./dify-broken -o /tmp/broken-a.difypkg
ERROR failed to create plugin decoder ... failed to read tool file: tools/does_not_exist.yaml
$ echo $?
1

# tool yaml extra.python.source pointing at a file that does not exist
$ dify-plugin plugin package ./dify-broken -o /tmp/broken-b.difypkg
INFO plugin packaged successfully
$ echo $?
0
$ ls -la /tmp/broken-b.difypkg
8499 bytes
```

Packaging validates the YAML graph and does not check that the Python it points
at exists.

### OpenClaw

```
$ pnpm --dir openclaw run build
$ pnpm --dir openclaw exec openclaw plugins build --entry ./dist/index.js --check
Plugin metadata is up to date.
$ pnpm --dir openclaw exec openclaw plugins validate --entry ./dist/index.js
Plugin page-stats is valid.
$ pnpm --dir openclaw test
Tests  18 passed (18)
```

openclaw 2026.7.1-2, typebox 1.3.16, vitest 3.2.7, Node 24.19.0. The tool is
driven through the same `api.registerTool` descriptor the Gateway builds. The
argument tests call `validateToolArguments` exported from
`openclaw/plugin-sdk/agent-core`, which is the function OpenClaw's agent loop
runs on every model-emitted tool call.

Drift detection was established by staling the generated manifest:

```
$ sed -i '' 's/"page_stats"/"page_stats_v2"/' openclaw.plugin.json
$ openclaw plugins validate --entry ./dist/index.js
openclaw.plugin.json generated metadata is stale. Run openclaw plugins build.
openclaw.plugin.json contracts.tools is missing: page_stats
openclaw.plugin.json contracts.tools has no matching defineToolPlugin tool: page_stats_v2
$ echo $?
1
```

`plugins build --entry ./dist/index.js --check` fails the same way, exit 1.

### Cross-language parity

```
$ diff <(.venv-langchain/bin/python scripts/parity.py) <(node scripts/parity.mjs)
$ echo $?
0
```

Identical title and word count at every truncation point from 100 to 552 bytes,
including cuts that land inside `<title>` and inside `<style>`.
`scripts/verify.sh` also diffs `langchain/src/dialects_page_stats/core.py`
against `dify/page_stats_core.py` and requires them byte-identical.

## Conclusions the README reaches

1. The three differ far less in what they can express than in where the
   expression is enforced. All three declare "integer between 1 and 60".
   LangChain enforces it inside the tool object, OpenClaw enforces it in the
   agent loop, Dify enforces it in a server that ships separately from the
   plugin.
2. Dify's plugin SDK enforces none of its own declarations.
   `Tool._convert_parameters` rewrites only values carrying a
   `dify_model_identity` marker, meaning files and tool selectors. Types,
   bounds, and required-ness in the YAML are a contract with the Dify server,
   not with the plugin process.
3. Dify has no tool-invocation exception type. `dify_plugin.errors.tool` ships
   only `ToolProviderCredentialValidationError` and `ToolProviderOAuthError`.
   Combined with `_invoke` being a generator, the workable failure path is to
   yield an error payload, which makes the invocation succeed. A 404, a timeout,
   and a healthy page are the same kind of event at the protocol level.
4. OpenClaw is the strictest contract. One file is the source of truth for
   identity, config schema, parameter schema, and behaviour; the manifest is
   generated from it; `plugins build --check` fails when it drifts; arguments
   are coerced and validated before `execute`; a throw becomes a model-visible
   error result that the runtime still knows is an error; cancellation is
   first-class through `context.signal`. The cost is an enforced Node version
   window and a regenerate-and-commit step on every schema change.
5. OpenClaw is the only one of the three that can stop work in flight.
   LangChain has no cancellation token and cannot have one, because `ainvoke`
   with only `_run` defined runs the blocking implementation on a worker thread.
6. Dify is the best of the three at configuration. It is the only one that
   separates developer wiring from operator input, gives the operator a form,
   and runs plugin code (`ToolProvider._validate_credentials`) to check what
   they typed before saving. The cost is that credential types are UI widget
   types, so `max_bytes` arrives as the string `"2000000"`.
7. Dify is the only one whose tool manifest declares the shape of the result
   (`output_schema`). Nothing in the plugin SDK checks the payload against it.
8. Contract-layer cost, excluding the shared core and tests: LangChain 74 lines
   in 1 file, OpenClaw 87 lines in 1 file plus a generated manifest, Dify 223
   lines across 6 files of which 125 are hand-maintained YAML.

## Judged worth doing, not done

**End-to-end runs inside a live Dify deployment and a live OpenClaw Gateway.**
Both need infrastructure this task does not have: Dify needs server, plugin
daemon, and database; OpenClaw needs a configured Gateway with a model provider
and credentials. What that would settle is narrow and named in the README: what
the Dify daemon does with an exception escaping `_invoke`, and what the Dify
server coerces before calling the plugin. Every other claim is made against code
that was actually executed here. OpenClaw ships an in-process harness at
`openclaw/plugin-sdk/plugin-test-api`, but its `package.json` `files` array
excludes it from the published package, so there is no supported substitute.

**A LangChain agent-loop run against a real model.** Needs a provider API key.
The tool-call path is covered instead by invoking with a tool call dict, which
is what an agent executor does, and by asserting the OpenAI tool schema.

**A CI workflow.** A GitHub Actions file that cannot be watched running is a
false signal, and verifying it means spending Actions minutes on a private repo
for a check that `scripts/verify.sh` already performs locally in one command.

## Environment note

This machine's Node is 24.13.0, below OpenClaw's floor of 24.15.0. Verification
used Node 24.19.0 unpacked into a scratch directory; the system installation was
not modified. `scripts/verify.sh` checks the running version up front and fails
with the acceptable ranges.

## Handoff

`callback_failed`. This task arrived without a dispatch envelope, so there is no
addressable session to return a receipt to, and guessing among the peer sessions
is not permitted. Receipt is recorded here instead.

- Done: all three implementations built, verified, and committed; README written.
- Output path: `/Users/suapril/Code/dialects`, pushed to `logxio/dialects` (private).
- Blocked: nothing.

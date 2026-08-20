# dialects

![License](https://img.shields.io/badge/license-MIT-blue)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Node](https://img.shields.io/badge/node-22.22%2B-blue)

One capability, implemented three times against three agent plugin contracts:
LangChain's `BaseTool`, Dify's manifest plus `_invoke`, and OpenClaw's
`defineToolPlugin`. The comparison below is the point. The code is the evidence
for it.

Every claim here came out of running the code. `./scripts/verify.sh` reproduces
all of it: 53 tests, a real Dify package build, a real OpenClaw manifest
validation, and a cross-language parity check, all against a local fixture
server with no network access and no API keys.

## The tool

`page_stats` fetches an http or https URL and reports the page title and the
number of words in its body. It takes a required `url` and an optional
`timeout_seconds` bounded to 1..60. It reads `user_agent` and `max_bytes` from
configuration. It has six named failures: `invalid_url`, `invalid_parameter`,
`timeout`, `unreachable`, `http_error`, `unsupported_content_type`.

That is small enough to read in one sitting and wide enough to hit every part of
a plugin contract that differs: schema declaration, structured results, error
taxonomy, configuration, cancellation, and discovery. The full contract is
[spec/page-stats.md](spec/page-stats.md), and all three implementations answer
to it, so anything that differs between them is a contract difference rather
than a behaviour difference.

The parse is pinned by that spec down to the entity table, so the three agree on
identical bytes including mid-document truncation:

```
bytes  title                              words
  100  Tide Tables & Other Regula             0
  150  Tide Tables & Other Regularities       0
  200  Tide Tables & Other Regularities       1
  300  Tide Tables & Other Regularities      17
  400  Tide Tables & Other Regularities      33
  552  Tide Tables & Other Regularities      37
```

## Running it

```bash
./scripts/verify.sh
```

Needs Python 3.10+, Node 22.22.3+ / 24.15+ / 25.9+, and pnpm. The Dify packaging
step needs the [Dify plugin CLI](https://github.com/langgenius/dify-plugin-daemon),
a single binary; without it that one step reports itself as skipped and the rest
still runs.

Versions this was checked against: langchain-core 1.6.0 and pydantic 2.13.4 on
CPython 3.13.14, dify_plugin 0.10.2 with Dify CLI 0.6.10, openclaw 2026.7.1-2
and typebox 1.3.16 on Node 24.19.0.

## The three shapes

LangChain. A pydantic model and a class, in one file. Nothing else exists.

```python
class PageStatsInput(BaseModel):
    url: str = Field(description="...")
    timeout_seconds: int = Field(default=10, ge=1, le=60, description="...")

class PageStatsTool(BaseTool):
    name: str = "page_stats"
    description: str = "..."
    args_schema: type[BaseModel] = PageStatsInput
    user_agent: str = DEFAULT_USER_AGENT      # configuration is tool state

    def _run(self, url, timeout_seconds=10, run_manager=None) -> dict:
        ...
        raise ToolException(json.dumps(payload))
```

Dify. Three YAML files declare the plugin; two Python files implement it.

```yaml
# tools/page_stats.yaml
parameters:
  - name: timeout_seconds
    type: number
    required: false
    default: 10
    min: 1
    max: 60
    form: llm
```

```python
class PageStatsTool(Tool):
    def _invoke(self, tool_parameters: dict) -> Generator[ToolInvokeMessage, None, None]:
        yield self.create_log_message(label="fetch", data={...}, status=LogStatus.START)
        ...
        yield self.create_json_message(payload)
```

OpenClaw. One TypeScript file, TypeBox for both schemas, manifest generated from
it.

```typescript
export default defineToolPlugin({
  id: "page-stats",
  configSchema: Type.Object({ userAgent: Type.Optional(Type.String()) }),
  tools: (tool) => [
    tool({
      name: "page_stats",
      parameters: Type.Object({
        url: Type.String({ description: "..." }),
        timeout_seconds: Type.Optional(Type.Integer({ minimum: 1, maximum: 60, default: 10 })),
      }),
      async execute(params, config, context) {
        context.signal?.throwIfAborted();
        ...
        throw new Error(JSON.stringify(payload));
      },
    }),
  ],
});
```

## Declaring inputs

All three can express "integer between 1 and 60". They differ in where that
declaration is enforced, and one of them does not enforce it in the plugin
process at all.

| | LangChain | Dify | OpenClaw |
| --- | --- | --- | --- |
| Schema written in | Python, pydantic | YAML | TypeScript, TypeBox |
| Bounds expressible | `ge` / `le` | `min` / `max` | `minimum` / `maximum` |
| Enforced before the tool body runs | yes, by pydantic inside `invoke` | no | yes, by the agent loop |
| `"30"` for an integer field | coerced to `30` | passed through as `"30"` | coerced to `30` |
| `999` against `max: 60` | `ValidationError` | passed through as `999` | rejected, message names `timeout_seconds` |
| Missing required field | `ValidationError` | reaches the tool body absent | rejected, message names `url` |
| Declared default applied | yes, pydantic fills `10` | not by the SDK | no, advisory to the model only |

LangChain validates in `BaseTool._parse_input`, so `_run` never sees a value the
schema forbids. `handle_validation_error` decides whether the caller or the
agent sees the failure, and it defaults to `False`.

OpenClaw validates in `validateToolArguments`, which the agent loop calls on
every model-emitted tool call. It runs TypeBox's `Value.Convert` first, then
`Check`, and on failure returns an error tool result whose text lists each
failing path. That function is exported from `openclaw/plugin-sdk/agent-core`,
so the tests here call the real one rather than a stand-in.

Dify is the outlier and the distinction matters. `Tool.invoke` calls
`_convert_parameters`, which rewrites only values carrying `dify_model_identity`
markers, that is files and tool selectors. Strings, numbers, and booleans arrive
exactly as sent. The `type`, `required`, `min`, and `max` fields in the tool
YAML are consumed by the Dify server and its UI, not by the plugin runtime. In a
deployed Dify the server does coerce and check before it calls you; the point is
that the plugin process has no such guarantee of its own, and nothing in the
package tells you which side you are trusting.

Concretely, this is the whole reason the shared core carries an
`invalid_parameter` branch. Only the Dify implementation can ever reach it.

## Returning results

| | LangChain | Dify | OpenClaw |
| --- | --- | --- | --- |
| The method returns | any Python object | a generator of `ToolInvokeMessage` | any JSON-compatible value, or a string |
| Caller of `.invoke()` gets | that object unchanged | the message stream | `{ content: [{ type: "text", text }], details }` |
| Model sees | `ToolMessage.content`, JSON-serialised | the JSON message | `JSON.stringify(payload, null, 2)` |
| Original object kept | only via `response_format="content_and_artifact"` | yes, `json_object` | yes, in `details` |
| Output schema declarable | no | yes, `output_schema` in the tool YAML | no |

LangChain gives the richest caller-side result and the thinnest model-side one.
`tool.invoke({...})` hands back the actual `dict`. Feed it a tool call instead
and you get a `ToolMessage` whose `content` is a JSON string, with the typed
object gone unless you opt into `content_and_artifact` and pull it out of
`artifact`.

OpenClaw's `defineToolPlugin` wraps the return automatically: a string becomes
text the model sees verbatim, anything else becomes pretty-printed JSON with the
original preserved in `details`. That split is the useful one, since the host UI
and the model want different things from the same result.

Dify is the only one of the three where the tool manifest declares the shape of
what comes back. `output_schema` sits next to the parameter declarations in the
tool YAML and is carried through into `ToolConfiguration`, so the platform has
it. Nothing in the plugin SDK checks the yielded payload against it.

## Reporting failures

This is the sharpest difference between the three, and it is not a matter of
taste.

| | LangChain | Dify | OpenClaw |
| --- | --- | --- | --- |
| Mechanism | `raise ToolException` | yield an error message | `throw` any `Error` |
| Dedicated exception type | `ToolException` | none for tool invocation | none needed |
| Default destination | re-raised at the caller | streamed as an ordinary result | caught by the agent loop |
| Model sees the failure | only if `handle_tool_error` is set | yes, as a successful result | yes, as the message text |
| Distinguishable from success | yes, `ToolMessage.status == "error"` | no, only by reading `ok` | yes, `isError: true` |

OpenClaw's path is the one to copy. `executePreparedToolCall` catches anything
thrown from `execute` and turns it into a tool result carrying that exact
message, flagged `isError`. The model gets told what went wrong and the runtime
knows it was a failure. You do not have to choose.

LangChain makes you choose, but at least it asks. `handle_tool_error` defaults
to `False`, so a `ToolException` propagates out of `invoke` and the application
deals with it. Set it to `True` and the same failure comes back as a
`ToolMessage` with `status="error"`. Both are reasonable; the default means an
unconfigured tool crashes the caller rather than informing the model.

Dify has no good option. `dify_plugin.errors.tool` ships exactly two exception
types, `ToolProviderCredentialValidationError` and `ToolProviderOAuthError`, and
both are about credentials. There is nothing for "this invocation failed".
Raising a plain exception is possible, but `_invoke` is a generator, so anything
already yielded has already been streamed and cannot be taken back. The workable
path is the one implemented here: yield a JSON message with `ok: false`. The
invocation then succeeds. A 404, a timeout, and a healthy page are the same kind
of event at the protocol level, separated only by a field the model has to
notice. That is the cost of making the return type a message stream without
adding an error message type to it.

One thing this repo does not settle: what a Dify deployment does with an
exception that escapes `_invoke`. That happens in the plugin daemon, which is
not run here.

## Configuration and credentials

| | LangChain | Dify | OpenClaw |
| --- | --- | --- | --- |
| Lives in | constructor arguments | provider credentials, `provider/*.yaml` | the plugin's Gateway config entry |
| Typed as | pydantic fields | UI widget types | TypeBox / JSON Schema |
| Numbers stay numbers | yes | no, arrive as strings | yes |
| Secrets | nothing built in | `secret-input`, plus OAuth hooks | `SecretRef` in the SDK |
| Validated at install time | no | yes, `ToolProvider._validate_credentials` | no |
| Filled in by | the application author | whoever installs the plugin | whoever edits the Gateway config |

Dify is clearly the best here and it is not close. It is the only one of the
three that separates "the developer wired this up" from "the operator supplied
this", gives the operator a form, and runs plugin code to check what they typed
before anything is saved. `_validate_credentials` runs once, at save time, with
the values in hand. The OAuth hooks on `ToolProvider` sit in the same place.

The cost shows up in the type column. Dify credential types are widget types,
not data types: `text-input`, `secret-input`, `select`, `boolean`,
`model-selector`, `app-selector`. A byte limit is a `text-input`, so `max_bytes`
reaches the tool as `"2000000"`, and every numeric setting needs an `int()` in
the plugin plus a validator in the provider to make that `int()` safe.

LangChain has no configuration concept at all. A `BaseTool` is a pydantic model,
so constructor fields work, which is elegant and gives you nothing for
operator-supplied settings. Whatever constructs the tool owns the problem.

## Long work, timeouts, cancellation

| | LangChain | Dify | OpenClaw |
| --- | --- | --- | --- |
| Cancellation signal | none | none | `context.signal`, an `AbortSignal` |
| Progress reporting | `run_manager` callbacks | yield log messages into the result stream | `context.onUpdate`, emitted as `tool_execution_update` |
| Framework-level timeout | none | `DifyPluginEnv(MAX_REQUEST_TIMEOUT=...)`, per plugin | the agent loop's signal |
| Async | `_arun`, or `_run` on a worker thread | generator, gevent-patched | async throughout |

OpenClaw is the only one that can stop work in flight. `execute` receives an
`AbortSignal`, passing it to `fetch` is one line, and an abort propagates as an
`AbortError` rather than being flattened into a result. The tests here abort a
three-second request after 50ms and assert that what comes back is an
`AbortError` and not an error payload, because a cancelled call has no result to
report.

Dify's timeout is real but blunt. `MAX_REQUEST_TIMEOUT` is set once in `main.py`
and applies to every invocation of every tool in the plugin. There is no
per-tool value and no way to ask for more time for one call. Its progress story
is the best of the three though, precisely because of the generator: log
messages and results travel the same ordered stream, so a long tool can narrate
itself without a side channel.

LangChain has neither. There is no cancellation token and no timeout; whatever
calls the tool wraps it. `run_manager` can report progress to callbacks. Only
`_run` is implemented here, and `ainvoke` still works, because LangChain runs
the sync implementation on a worker thread. That is convenient and it is also
why cancellation cannot exist: nothing can interrupt a blocking socket read on a
thread you do not own.

## Discovery and registration

| | LangChain | Dify | OpenClaw |
| --- | --- | --- | --- |
| How the host finds the tool | it does not; you construct it and pass it in | `manifest.yaml` to provider YAML to tool YAML, then imports the class by path | reads `openclaw.plugin.json`, whose `contracts.tools` names every tool |
| Code imported to discover | all of it | provider and tool modules | none |
| Manifest is | n/a | hand-written, three files | generated by `openclaw plugins build` |
| Drift caught by | n/a | packaging catches broken YAML paths only | `plugins build --check` and `plugins validate` |

OpenClaw's design is the one worth stealing. Metadata is derived from the same
`defineToolPlugin` call that defines behaviour, written to disk by a generator,
and checked in CI:

```
$ openclaw plugins validate --entry ./dist/index.js
openclaw.plugin.json generated metadata is stale. Run openclaw plugins build.
openclaw.plugin.json contracts.tools is missing: page_stats
openclaw.plugin.json contracts.tools has no matching defineToolPlugin tool: page_stats_v2
$ echo $?
1
```

`contracts.tools` is what makes it worth the generator step: the Gateway can
answer "which plugin owns `page_stats`" without importing any plugin's runtime
code.

Dify walks a YAML graph and then imports Python by path from
`extra.python.source`. Packaging validates the graph but not the code it points
at. Break a tool YAML path and `dify plugin package` refuses, exit 1. Point
`extra.python.source` at a file that does not exist and it packages happily,
8499 bytes, exit 0. That failure surfaces when the daemon tries to load the
class, which is after install.

LangChain has no discovery layer, which is the honest answer for a library
rather than a host. There is no manifest to go stale because there is no
manifest.

## What it costs to write

Contract-layer lines, excluding the shared fetching and parsing core and
excluding tests.

| | Files | Lines | Hand-written manifest |
| --- | ---: | ---: | ---: |
| LangChain | 1 | 74 | 0 |
| OpenClaw | 1 | 87 | 0, generated |
| Dify | 6 | 223 | 125 lines of YAML |

The Dify number is not padding. Every tool needs a `label` and a
`human_description` per locale, a separate `llm_description`, and a `form`
value, and every one of those lives in a different file from the code that reads
it. Renaming a parameter means editing YAML and Python and having nothing tell
you when you miss one.

## Verdicts

**Strictest: OpenClaw.** One file is the single source of truth for identity,
config schema, parameter schema, and behaviour. The manifest is generated from
it and `plugins build --check` fails when it drifts. Arguments are coerced and
validated before `execute` runs. A throw becomes a model-visible error result
that the runtime still knows is an error. Cancellation is first-class. The cost
is a Node version window the CLI enforces (22.22.3+, 24.15+, or 25.9+) and a
regenerate-and-commit step every time an id, name, or schema changes. That step
is the price of the guarantee, and it is cheap.

**Loosest: Dify, on the plugin side.** It declares the most of the three:
parameter types, bounds, credential schema, and an output schema. Its SDK
enforces none of it. The declarations are a contract with the Dify server, not
with your code, and nothing in the package makes that boundary visible. Combined
with a generator return type that has no error message kind, the default failure
path is a successful invocation carrying an error object. The risk is a plugin
that looks fully specified and validates nothing, where a wrong-typed parameter
and a dead host produce the same shape of output.

**In between: LangChain.** Validation is real and happens before your code runs.
Everything else is convention. No manifest, no discovery, no configuration
story, no cancellation, no timeout. That is the correct set of features for a
library that hands you an object and lets the application decide the rest, and
it is why LangChain has the shortest contract layer of the three. It stops
being correct the moment you need someone other than the developer to install
and configure the thing.

The general shape: the three differ far less in what they can express than in
where the expression is enforced. All three declare the same bound. LangChain
enforces it in the tool object, OpenClaw enforces it in the agent loop, and
Dify enforces it in a server that ships separately from the plugin. If you are
choosing between them, that is the axis to choose on, because it decides who is
holding the bag when a model sends `"soon"` where you asked for a number.

## Layout

```
spec/page-stats.md    the contract all three implement
fixtures/             HTML documents and two fixture servers, one per language
langchain/            BaseTool implementation and 18 tests
dify/                 manifest, provider, tool, and 17 tests
openclaw/             defineToolPlugin implementation and 18 tests
scripts/verify.sh     runs everything above
```

The fetching and parsing core is duplicated rather than shared:
`langchain/src/dialects_page_stats/core.py` and `dify/page_stats_core.py` are
byte-identical, and `openclaw/src/core.ts` is the same algorithm in TypeScript.
Sharing it would need a package neither Dify's nor OpenClaw's distribution model
accepts, since both ship self-contained. `scripts/verify.sh` diffs the two
Python copies and runs `scripts/parity.py` against `scripts/parity.mjs`, so
drift fails the build rather than relying on discipline.

## License

MIT

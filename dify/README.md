# page_stats for Dify

A Dify tool plugin that fetches an http or https URL and reports the page title
and body word count. The contract it implements is
[../spec/page-stats.md](../spec/page-stats.md).

Requires Python 3.12 or later, which is what `meta.runner.version` in the
manifest pins. Tested against dify_plugin 0.10.2 on CPython 3.13.14, and
packaged with the Dify CLI 0.6.10.

## Layout

Dify discovers a plugin by reading YAML, not by importing code. Three files
declare the plugin and two implement it.

| File | Lines | What it is |
| --- | ---: | --- |
| `manifest.yaml` | 28 | Plugin identity, resource limits, runner, and the path to the provider |
| `provider/page_stats.yaml` | 36 | Provider identity, credential schema, and the path to the tool |
| `tools/page_stats.yaml` | 61 | Tool identity, parameter declarations, output schema |
| `provider/page_stats.py` | 26 | Credential validation, run once at install time |
| `tools/page_stats.py` | 63 | `_invoke`, a generator of `ToolInvokeMessage` |
| `main.py` | 9 | Entry point; sets the daemon's per-invocation timeout |
| `page_stats_core.py` | 190 | Fetching and parsing, framework-free |

`page_stats_core.py` is byte-identical to
`langchain/src/dialects_page_stats/core.py`. Each plugin has to ship
self-contained, so the file is duplicated rather than shared, and
`scripts/verify.sh` diffs the two copies.

## Package

```bash
dify plugin package ./dify
```

The CLI is a single binary from the
[dify-plugin-daemon](https://github.com/langgenius/dify-plugin-daemon) releases.
It produces a `.difypkg` you upload to a Dify instance.

## Configure

`user_agent` and `max_bytes` are provider credentials. Whoever installs the
plugin fills them in once; the model never sees them and cannot change them per
call. Both arrive at the tool as strings, because Dify credential types are UI
widget types rather than data types.

## Tests

```bash
pip install -r requirements.txt pytest && pytest tests
```

The manifest tests validate the YAML against the pydantic models that ship in
`dify_plugin`, which is the same code the plugin daemon loads them with. The
runtime tests drive the tool through `Tool.from_credentials` and the SDK's own
class loader, against a local fixture server from `../fixtures/`.

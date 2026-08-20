# page_stats for LangChain

A `BaseTool` that fetches an http or https URL and reports the page title and
body word count. The contract it implements is [../spec/page-stats.md](../spec/page-stats.md).

Requires Python 3.10 or later. Tested against langchain-core 1.6.0 and pydantic
2.13.4 on CPython 3.13.14.

## Install

```bash
pip install -e .
```

`langchain-core` is the only runtime dependency. Fetching and parsing use the
standard library.

## Use

```python
from dialects_page_stats import PageStatsTool

tool = PageStatsTool()
tool.invoke({"url": "https://example.com"})
```

Configuration is constructor state, because `BaseTool` is itself a pydantic
model:

```python
tool = PageStatsTool(user_agent="my-agent/2.0", max_bytes=500_000)
```

Failures raise `ToolException` carrying the spec's error payload as JSON.
LangChain re-raises it at the caller unless you opt in:

```python
tool = PageStatsTool(handle_tool_error=True)
```

With that set, and a tool call rather than a bare argument dict as input, the
failure comes back as a `ToolMessage` with `status="error"` and the payload as
its content.

## Files

| File | Lines | What it is |
| --- | ---: | --- |
| `src/dialects_page_stats/tool.py` | 74 | The entire LangChain contract: args schema, tool class, failure channel |
| `src/dialects_page_stats/core.py` | 190 | Fetching and parsing, framework-free |
| `tests/test_contract.py` | 190 | Every claim the root README makes about LangChain |

## Tests

```bash
pip install -e ".[test]" && pytest
```

The tests run against a local fixture server from `../fixtures/`. No network
access and no API keys.

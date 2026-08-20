"""What LangChain's contract actually does, run against a local fixture server.

Every claim the root README makes about the LangChain column is asserted here.
"""

import asyncio
import json
import socket

import pytest
from langchain_core.messages import ToolMessage
from langchain_core.tools import ToolException
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import ValidationError

from dialects_page_stats import PageStatsTool

ARTICLE_WORDS = 37
ARTICLE_TITLE = "Tide Tables & Other Regularities"


def closed_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


# --- results ---------------------------------------------------------------


def test_success_returns_a_dict_not_a_string(base_url):
    result = PageStatsTool().invoke({"url": f"{base_url}/article"})

    assert isinstance(result, dict)
    assert result["ok"] is True
    assert result["title"] == ARTICLE_TITLE
    assert result["word_count"] == ARTICLE_WORDS
    assert result["status"] == 200
    assert result["truncated"] is False


def test_redirect_is_reported_in_final_url(base_url):
    result = PageStatsTool().invoke({"url": f"{base_url}/redirect"})

    assert result["url"] == f"{base_url}/redirect"
    assert result["final_url"] == f"{base_url}/article"
    assert result["word_count"] == ARTICLE_WORDS


def test_missing_title_is_null(base_url):
    result = PageStatsTool().invoke({"url": f"{base_url}/no-title"})

    assert result["title"] is None
    assert result["word_count"] == 4


def test_max_bytes_is_tool_state_and_truncates(base_url):
    result = PageStatsTool(max_bytes=200).invoke({"url": f"{base_url}/article"})

    assert result["truncated"] is True
    assert result["word_count"] < ARTICLE_WORDS


# --- failures --------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "error_code"),
    [
        ("/not-found", "http_error"),
        ("/binary", "unsupported_content_type"),
    ],
)
def test_failures_raise_tool_exception(base_url, path, error_code):
    with pytest.raises(ToolException) as excinfo:
        PageStatsTool().invoke({"url": f"{base_url}{path}"})

    assert json.loads(str(excinfo.value))["error_code"] == error_code


def test_timeout_raises_tool_exception(base_url):
    with pytest.raises(ToolException) as excinfo:
        PageStatsTool().invoke({"url": f"{base_url}/slow?ms=3000", "timeout_seconds": 1})

    assert json.loads(str(excinfo.value))["error_code"] == "timeout"


def test_unreachable_raises_tool_exception():
    with pytest.raises(ToolException) as excinfo:
        PageStatsTool().invoke({"url": f"http://127.0.0.1:{closed_port()}/article"})

    assert json.loads(str(excinfo.value))["error_code"] == "unreachable"


def test_invalid_url_raises_tool_exception():
    with pytest.raises(ToolException) as excinfo:
        PageStatsTool().invoke({"url": "not-a-url"})

    assert json.loads(str(excinfo.value))["error_code"] == "invalid_url"


def test_handle_tool_error_turns_the_failure_into_a_tool_message(base_url):
    tool = PageStatsTool(handle_tool_error=True)

    message = tool.invoke(
        {
            "name": "page_stats",
            "args": {"url": f"{base_url}/not-found"},
            "id": "call_1",
            "type": "tool_call",
        }
    )

    assert isinstance(message, ToolMessage)
    assert message.status == "error"
    assert json.loads(message.content)["error_code"] == "http_error"


def test_a_dict_result_is_json_serialised_into_the_tool_message(base_url):
    """A dict survives .invoke(), but a ToolMessage carries it as JSON text."""
    message = PageStatsTool().invoke(
        {
            "name": "page_stats",
            "args": {"url": f"{base_url}/article"},
            "id": "call_1",
            "type": "tool_call",
        }
    )

    assert isinstance(message.content, str)
    assert message.status == "success"
    assert json.loads(message.content)["word_count"] == ARTICLE_WORDS


# --- schema ----------------------------------------------------------------


def test_pydantic_rejects_out_of_range_timeout_before_run(base_url):
    with pytest.raises(ValidationError) as excinfo:
        PageStatsTool().invoke({"url": f"{base_url}/article", "timeout_seconds": 999})

    assert "less_than_equal" in str(excinfo.value)


def test_pydantic_coerces_a_numeric_string(base_url):
    """Non-strict pydantic accepts "30" where the schema says integer."""
    result = PageStatsTool().invoke(
        {"url": f"{base_url}/article", "timeout_seconds": "30"}
    )

    assert result["ok"] is True


def test_pydantic_rejects_a_non_numeric_string(base_url):
    with pytest.raises(ValidationError):
        PageStatsTool().invoke({"url": f"{base_url}/article", "timeout_seconds": "soon"})


def test_missing_required_url_is_rejected():
    with pytest.raises(ValidationError):
        PageStatsTool().invoke({"timeout_seconds": 5})


def test_pydantic_fills_the_declared_default(base_url):
    seen = {}

    class Recording(PageStatsTool):
        def _run(self, url, timeout_seconds=None, run_manager=None):
            seen["timeout_seconds"] = timeout_seconds
            return {}

    Recording().invoke({"url": f"{base_url}/article"})

    assert seen["timeout_seconds"] == 10


def test_ainvoke_works_without_an_async_implementation(base_url):
    """Only _run is defined; LangChain runs it off the event loop for ainvoke."""
    result = asyncio.run(PageStatsTool().ainvoke({"url": f"{base_url}/article"}))

    assert result["word_count"] == ARTICLE_WORDS


def test_the_schema_the_model_sees():
    schema = convert_to_openai_tool(PageStatsTool())["function"]

    assert schema["name"] == "page_stats"
    assert schema["parameters"]["required"] == ["url"]
    assert schema["parameters"]["properties"]["timeout_seconds"]["maximum"] == 60
    assert schema["parameters"]["properties"]["timeout_seconds"]["minimum"] == 1

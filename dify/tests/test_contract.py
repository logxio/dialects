"""What Dify's contract actually does, run against a local fixture server.

The manifest tests validate the YAML against the pydantic models that ship in
dify_plugin, which is the same code the plugin daemon loads them with. The
runtime tests drive the tool through Tool.from_credentials and the SDK's own
class loader, so nothing here depends on the shape of the plugin being guessed.
"""

import socket
from pathlib import Path

import pytest
import yaml
from dify_plugin import Tool, ToolProvider
from dify_plugin.core.entities.plugin.setup import PluginConfiguration
from dify_plugin.core.utils.class_loader import load_single_subclass_from_source
from dify_plugin.entities.invoke_message import InvokeMessage
from dify_plugin.entities.tool import ToolParameter, ToolProviderConfiguration
from dify_plugin.errors.tool import ToolProviderCredentialValidationError

ARTICLE_WORDS = 37
ARTICLE_TITLE = "Tide Tables & Other Regularities"

LogStatus = InvokeMessage.LogMessage.LogStatus
MessageType = InvokeMessage.MessageType


def closed_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def load_tool_class() -> type[Tool]:
    """Exactly how the daemon finds the class: by path, from extra.python.source."""
    return load_single_subclass_from_source(
        module_name="tools.page_stats",
        script_path=str(Path.cwd() / "tools" / "page_stats.py"),
        parent_type=Tool,
    )


def load_provider_class() -> type[ToolProvider]:
    return load_single_subclass_from_source(
        module_name="provider.page_stats",
        script_path=str(Path.cwd() / "provider" / "page_stats.py"),
        parent_type=ToolProvider,
    )


def run(credentials: dict, parameters: dict) -> list:
    tool = load_tool_class().from_credentials(credentials)
    return list(tool.invoke(parameters))


def json_payload(messages: list) -> dict:
    payloads = [m for m in messages if m.type == MessageType.JSON]
    assert len(payloads) == 1, "the tool yields exactly one result message"
    return dict(payloads[0].message.json_object)


# --- manifests -------------------------------------------------------------


def test_manifest_matches_the_sdk_model():
    manifest = PluginConfiguration.model_validate(
        yaml.safe_load(Path("manifest.yaml").read_text())
    )

    assert manifest.plugins.tools == ["provider/page_stats.yaml"]
    assert manifest.meta.runner.entrypoint == "main"


def test_provider_manifest_matches_the_sdk_model():
    provider = ToolProviderConfiguration.model_validate(
        yaml.safe_load(Path("provider/page_stats.yaml").read_text())
    )

    assert provider.identity.name == "page_stats"
    assert {c.name for c in provider.credentials_schema} == {"user_agent", "max_bytes"}
    assert provider.extra.python.source == "provider/page_stats.py"


def test_the_declared_parameters_are_the_ones_the_model_sees():
    provider = ToolProviderConfiguration.model_validate(
        yaml.safe_load(Path("provider/page_stats.yaml").read_text())
    )
    parameters = {p.name: p for p in provider.tools[0].parameters}

    assert parameters["url"].required is True
    assert parameters["url"].form is ToolParameter.ToolParameterForm.LLM
    assert parameters["timeout_seconds"].required is False
    assert parameters["timeout_seconds"].min == 1
    assert parameters["timeout_seconds"].max == 60


def test_the_tool_declares_its_output_schema():
    provider = ToolProviderConfiguration.model_validate(
        yaml.safe_load(Path("provider/page_stats.yaml").read_text())
    )

    assert provider.tools[0].output_schema["properties"]["word_count"] == {
        "type": "integer"
    }


# --- results ---------------------------------------------------------------


def test_success_is_a_json_message(base_url):
    messages = run({}, {"url": f"{base_url}/article"})
    result = json_payload(messages)

    assert result["ok"] is True
    assert result["title"] == ARTICLE_TITLE
    assert result["word_count"] == ARTICLE_WORDS
    assert result["status"] == 200


def test_progress_and_result_share_one_stream(base_url):
    messages = run({}, {"url": f"{base_url}/article"})
    kinds = [m.type for m in messages]

    assert kinds == [MessageType.LOG, MessageType.LOG, MessageType.JSON]
    assert messages[0].message.status is LogStatus.START
    assert messages[1].message.status is LogStatus.SUCCESS


def test_redirect_is_reported_in_final_url(base_url):
    result = json_payload(run({}, {"url": f"{base_url}/redirect"}))

    assert result["final_url"] == f"{base_url}/article"


def test_credentials_supply_configuration(base_url):
    result = json_payload(
        run({"max_bytes": "200"}, {"url": f"{base_url}/article"})
    )

    assert result["truncated"] is True


def test_credentials_arrive_as_strings(base_url):
    """Dify credential types are UI widgets, so a number is typed as text-input."""
    provider = ToolProviderConfiguration.model_validate(
        yaml.safe_load(Path("provider/page_stats.yaml").read_text())
    )
    max_bytes = next(c for c in provider.credentials_schema if c.name == "max_bytes")

    assert max_bytes.type.value == "text-input"
    assert max_bytes.default == "2000000"


# --- failures --------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "error_code"),
    [
        ("/not-found", "http_error"),
        ("/binary", "unsupported_content_type"),
    ],
)
def test_failures_come_back_as_a_successful_invocation(base_url, path, error_code):
    messages = run({}, {"url": f"{base_url}{path}"})
    result = json_payload(messages)

    assert result["ok"] is False
    assert result["error_code"] == error_code
    assert messages[1].message.status is LogStatus.ERROR


def test_timeout(base_url):
    result = json_payload(
        run({}, {"url": f"{base_url}/slow?ms=3000", "timeout_seconds": 1})
    )

    assert result["error_code"] == "timeout"


def test_unreachable():
    result = json_payload(run({}, {"url": f"http://127.0.0.1:{closed_port()}/article"}))

    assert result["error_code"] == "unreachable"


def test_a_missing_required_parameter_reaches_the_tool_body(base_url):
    """required: true is enforced by the Dify server, not by the plugin SDK."""
    result = json_payload(run({}, {}))

    assert result["error_code"] == "invalid_url"


# --- what the SDK does and does not do to parameters -----------------------


def test_the_sdk_does_not_coerce_declared_types(base_url):
    """type: number in the YAML does not make the SDK convert "30" to 30."""
    result = json_payload(
        run({}, {"url": f"{base_url}/article", "timeout_seconds": "30"})
    )

    assert result["error_code"] == "invalid_parameter"


def test_the_sdk_does_not_enforce_declared_bounds(base_url):
    """min/max in the YAML do not make the SDK reject 999."""
    result = json_payload(
        run({}, {"url": f"{base_url}/article", "timeout_seconds": 999})
    )

    assert result["error_code"] == "invalid_parameter"


# --- credentials -----------------------------------------------------------


def test_the_provider_validates_credentials_at_install_time():
    provider = load_provider_class()()

    with pytest.raises(ToolProviderCredentialValidationError):
        provider.validate_credentials({"max_bytes": "not-a-number"})

    provider.validate_credentials({"max_bytes": "500000"})

"""The Dify contract surface for page_stats.

_invoke is a generator. Dify streams every message it yields, in order, which is
why progress and result are the same channel here. Credentials arrive through
self.runtime, already validated by the provider.

The failure path yields a JSON message rather than raising: a generator that has
already yielded cannot un-yield, and the Dify plugin SDK has no tool-invocation
exception type. See the root README for what that costs.
"""

from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.invoke_message import InvokeMessage
from dify_plugin.entities.tool import ToolInvokeMessage

from page_stats_core import (
    DEFAULT_MAX_BYTES,
    DEFAULT_TIMEOUT_SECONDS,
    DEFAULT_USER_AGENT,
    PageStatsError,
    fetch_page_stats,
)

LogStatus = InvokeMessage.LogMessage.LogStatus


class PageStatsTool(Tool):
    def _invoke(
        self, tool_parameters: dict[str, Any]
    ) -> Generator[ToolInvokeMessage, None, None]:
        credentials = self.runtime.credentials or {}
        user_agent = str(credentials.get("user_agent") or "").strip() or DEFAULT_USER_AGENT
        max_bytes = int(credentials.get("max_bytes") or DEFAULT_MAX_BYTES)

        url = tool_parameters.get("url")
        timeout_seconds = tool_parameters.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)

        started = self.create_log_message(
            label="fetch",
            data={"url": url, "timeout_seconds": timeout_seconds},
            status=LogStatus.START,
        )
        yield started

        try:
            result = fetch_page_stats(
                url,
                timeout_seconds=timeout_seconds,
                user_agent=user_agent,
                max_bytes=max_bytes,
            )
        except PageStatsError as exc:
            yield self.finish_log_message(
                log=started, status=LogStatus.ERROR, error=exc.message
            )
            yield self.create_json_message(exc.to_dict())
            return

        yield self.finish_log_message(log=started, status=LogStatus.SUCCESS)
        yield self.create_json_message(result)

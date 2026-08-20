"""The LangChain contract surface for page_stats.

Everything here is LangChain: a pydantic args schema, a BaseTool subclass, and
ToolException as the failure channel. The fetching lives in core.py.
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.callbacks import CallbackManagerForToolRun
from langchain_core.tools import BaseTool, ToolException
from pydantic import BaseModel, Field

from dialects_page_stats.core import (
    DEFAULT_MAX_BYTES,
    DEFAULT_TIMEOUT_SECONDS,
    DEFAULT_USER_AGENT,
    MAX_TIMEOUT_SECONDS,
    MIN_TIMEOUT_SECONDS,
    PageStatsError,
    fetch_page_stats,
)


class PageStatsInput(BaseModel):
    """What the model is allowed to send."""

    url: str = Field(description="Absolute http or https URL of the page to read.")
    timeout_seconds: int = Field(
        default=DEFAULT_TIMEOUT_SECONDS,
        ge=MIN_TIMEOUT_SECONDS,
        le=MAX_TIMEOUT_SECONDS,
        description="How long to wait for the response, in seconds.",
    )


class PageStatsTool(BaseTool):
    """Read a web page and report its title and word count.

    Configuration is constructor state, because a BaseTool is a pydantic model:

        tool = PageStatsTool(user_agent="my-agent/2.0", max_bytes=500_000)
    """

    name: str = "page_stats"
    description: str = (
        "Fetch a web page over http or https and report its title and the number "
        "of words in its body. Use it to check what a URL actually contains "
        "before deciding whether to read the whole thing."
    )
    args_schema: type[BaseModel] = PageStatsInput

    user_agent: str = DEFAULT_USER_AGENT
    max_bytes: int = DEFAULT_MAX_BYTES

    def _run(
        self,
        url: str,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        run_manager: CallbackManagerForToolRun | None = None,
    ) -> dict[str, Any]:
        try:
            return fetch_page_stats(
                url,
                timeout_seconds=timeout_seconds,
                user_agent=self.user_agent,
                max_bytes=self.max_bytes,
            )
        except PageStatsError as exc:
            # ToolException is the one exception type LangChain treats as a tool
            # result rather than a crash, and only when handle_tool_error is set.
            raise ToolException(json.dumps(exc.to_dict())) from exc

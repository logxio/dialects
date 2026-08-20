"""Provider-level credential handling.

Dify calls _validate_credentials once, when someone saves the provider settings
in the UI. Neither LangChain nor OpenClaw has an equivalent install-time hook.
"""

from typing import Any

from dify_plugin import ToolProvider
from dify_plugin.errors.tool import ToolProviderCredentialValidationError

from page_stats_core import DEFAULT_MAX_BYTES


class PageStatsProvider(ToolProvider):
    def _validate_credentials(self, credentials: dict[str, Any]) -> None:
        raw = credentials.get("max_bytes") or DEFAULT_MAX_BYTES
        try:
            max_bytes = int(raw)
        except (TypeError, ValueError) as exc:
            msg = f"max_bytes must be a whole number, got {raw!r}."
            raise ToolProviderCredentialValidationError(msg) from exc

        if max_bytes < 1:
            msg = f"max_bytes must be at least 1, got {max_bytes}."
            raise ToolProviderCredentialValidationError(msg)

"""Fetch an http(s) URL and report its title and body word count.

Framework-free. Nothing in this module knows which agent runtime is calling it;
the framework-specific code lives beside it. Failures are raised as
PageStatsError so the contract layer decides how an agent sees them.

The algorithm is fixed by spec/page-stats.md. This file is duplicated verbatim
in langchain/ and dify/ because each plugin has to ship self-contained, and
openclaw/src/core.ts is the same algorithm in TypeScript. scripts/verify.sh
diffs the two Python copies so they cannot drift.
"""

from __future__ import annotations

import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

DEFAULT_USER_AGENT = "dialects-page-stats/1.0"
DEFAULT_MAX_BYTES = 2_000_000
DEFAULT_TIMEOUT_SECONDS = 10
MIN_TIMEOUT_SECONDS = 1
MAX_TIMEOUT_SECONDS = 60

HTML_CONTENT_TYPES = ("text/html", "application/xhtml+xml")

_TITLE = re.compile(r"<title\b[^>]*>(.*?)(?:</title\s*>|\Z)", re.IGNORECASE | re.DOTALL)
_DROPPED = re.compile(
    r"<(script|style|title)\b[^>]*>.*?(?:</\1\s*>|\Z)", re.IGNORECASE | re.DOTALL
)
_TAG = re.compile(r"<[^>]*>")
_NUMERIC_ENTITY = re.compile(r"&#(x[0-9a-fA-F]+|[0-9]+);")
_NAMED_ENTITIES = {
    "&amp;": "&",
    "&lt;": "<",
    "&gt;": ">",
    "&quot;": '"',
    "&#39;": "'",
    "&nbsp;": " ",
}


class PageStatsError(Exception):
    """A failure that carries a machine-readable code alongside its message."""

    def __init__(self, error_code: str, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.extra = extra

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": False,
            "error_code": self.error_code,
            "message": self.message,
            **self.extra,
        }


@dataclass(frozen=True)
class ParsedPage:
    title: str | None
    word_count: int


def _decode_entities(text: str) -> str:
    for entity, char in _NAMED_ENTITIES.items():
        text = text.replace(entity, char)

    def replace(match: re.Match[str]) -> str:
        raw = match.group(1)
        code = int(raw[1:], 16) if raw[0] in "xX" else int(raw)
        try:
            return chr(code)
        except ValueError:
            return match.group(0)

    return _NUMERIC_ENTITY.sub(replace, text)


def parse_html(html: str) -> ParsedPage:
    """Apply the fixed parse of spec/page-stats.md."""
    title = None
    match = _TITLE.search(html)
    if match:
        candidate = " ".join(_decode_entities(_TAG.sub("", match.group(1))).split())
        title = candidate or None

    body = _DROPPED.sub(" ", html)
    body = _TAG.sub(" ", body)
    body = _decode_entities(body)
    return ParsedPage(title=title, word_count=len(body.split()))


def _is_html(content_type: str) -> bool:
    return content_type.split(";")[0].strip().lower() in HTML_CONTENT_TYPES


def validate_timeout(value: Any) -> int:
    """Check timeout_seconds the way the spec's table says, and return it as int.

    A framework whose schema layer enforces the bound never reaches the raise.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PageStatsError(
            "invalid_parameter",
            f"timeout_seconds must be a number, got {type(value).__name__}.",
        )
    if isinstance(value, float) and not value.is_integer():
        raise PageStatsError(
            "invalid_parameter",
            f"timeout_seconds must be a whole number of seconds, got {value}.",
        )
    seconds = int(value)
    if not MIN_TIMEOUT_SECONDS <= seconds <= MAX_TIMEOUT_SECONDS:
        raise PageStatsError(
            "invalid_parameter",
            f"timeout_seconds must be between {MIN_TIMEOUT_SECONDS} and "
            f"{MAX_TIMEOUT_SECONDS}, got {seconds}.",
        )
    return seconds


def fetch_page_stats(
    url: str,
    *,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    user_agent: str = DEFAULT_USER_AGENT,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> dict[str, Any]:
    """Fetch url and return the success payload of spec/page-stats.md.

    Raises PageStatsError on every failure the spec names.
    """
    if not isinstance(url, str):
        raise PageStatsError("invalid_url", f"url must be a string, got {type(url).__name__}.")

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise PageStatsError("invalid_url", f"Not an absolute http(s) URL: {url!r}.")

    timeout_seconds = validate_timeout(timeout_seconds)

    request = urllib.request.Request(url, headers={"User-Agent": user_agent})
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            content_type = response.headers.get("Content-Type", "")
            if not _is_html(content_type):
                raise PageStatsError(
                    "unsupported_content_type",
                    f"Expected HTML, got {content_type or 'no Content-Type'}.",
                    content_type=content_type,
                )
            raw = response.read(max_bytes + 1)
            final_url = response.geturl()
            status = response.status
    except PageStatsError:
        raise
    except urllib.error.HTTPError as exc:
        raise PageStatsError(
            "http_error", f"Server returned {exc.code}.", status=exc.code
        ) from exc
    except TimeoutError as exc:
        raise PageStatsError(
            "timeout", f"No response within {timeout_seconds}s."
        ) from exc
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, TimeoutError):
            raise PageStatsError(
                "timeout", f"No response within {timeout_seconds}s."
            ) from exc
        raise PageStatsError("unreachable", f"Could not reach {url}: {exc.reason}.") from exc
    except OSError as exc:
        raise PageStatsError("unreachable", f"Could not reach {url}: {exc}.") from exc

    page = parse_html(raw[:max_bytes].decode("utf-8", errors="replace"))
    return {
        "ok": True,
        "url": url,
        "final_url": final_url,
        "status": status,
        "content_type": content_type,
        "title": page.title,
        "word_count": page.word_count,
        "truncated": len(raw) > max_bytes,
    }

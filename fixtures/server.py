"""Fixture HTTP server shared by the Python test suites.

Serves the documents in fixtures/pages/ plus the routes that make a fetching
tool fail: a redirect, a slow response, a 404, and a non-HTML body. Standard
library only, binds an ephemeral port.

Standalone:
    python fixtures/server.py
"""

from __future__ import annotations

import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

PAGES = Path(__file__).resolve().parent / "pages"

# Bytes that no HTML parser should be asked to read.
BINARY_BODY = b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\nendobj\n"


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args: object) -> None:  # noqa: D102 - silence stderr
        pass

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        parsed = urlparse(self.path)
        route = parsed.path

        if route == "/article":
            self._send(200, (PAGES / "article.html").read_bytes(), "text/html; charset=utf-8")
        elif route == "/no-title":
            self._send(200, (PAGES / "no-title.html").read_bytes(), "text/html; charset=utf-8")
        elif route == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/article")
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif route == "/slow":
            delay_ms = int(parse_qs(parsed.query).get("ms", ["3000"])[0])
            time.sleep(delay_ms / 1000)
            self._send(200, (PAGES / "article.html").read_bytes(), "text/html; charset=utf-8")
        elif route == "/not-found":
            self._send(404, b"<html><body>gone</body></html>", "text/html; charset=utf-8")
        elif route == "/binary":
            self._send(200, BINARY_BODY, "application/pdf")
        else:
            self._send(404, b"<html><body>no route</body></html>", "text/html; charset=utf-8")


class FixtureServer:
    """Threaded fixture server. Use as a context manager."""

    def __init__(self) -> None:
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        host, port = self._httpd.server_address[:2]
        return f"http://{host}:{port}"

    def __enter__(self) -> "FixtureServer":
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=5)


if __name__ == "__main__":
    with FixtureServer() as server:
        sys.stdout.write(f"{server.base_url}\n")
        sys.stdout.flush()
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass

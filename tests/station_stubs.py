"""Stub HTTP servers used by the Amosclaud Model Station agent tests."""

from __future__ import annotations

import json
import socket
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class _StubHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args) -> None:  # keep pytest output clean
        return

    def _dispatch(self, method: str) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            body = raw.decode("utf-8", "replace")
        path = self.path.split("?", 1)[0]
        record = {
            "method": method,
            "path": path,
            "headers": dict(self.headers),
            "body": body,
        }
        self.server.requests.append(record)
        route = self.server.routes.get((method, path))
        if route is None:
            self._write(404, {"detail": f"no stub route for {method} {path}"})
            return
        status, payload = route(record) if callable(route) else route
        self._write(status, payload)

    def _write(self, status: int, payload) -> None:
        data = b"" if payload is None and status == 204 else json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if data:
            self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        self._dispatch("GET")

    def do_POST(self) -> None:  # noqa: N802 - http.server API
        self._dispatch("POST")


@contextmanager
def stub_server(routes: dict):
    """Serve ``routes`` on a random localhost port and record every request."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _StubHandler)
    server.routes = dict(routes)
    server.requests = []
    server.url = f"http://127.0.0.1:{server.server_port}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def ollama_routes(model: str, reply: str = "stub reply", *, chat=None, tags=None) -> dict:
    """Default Ollama stub: one installed model and a fixed chat reply."""
    return {
        ("GET", "/api/tags"): tags
        or (lambda _record: (200, {"models": [{"name": model, "size": 1}]})),
        ("POST", "/api/chat"): chat
        or (
            lambda _record: (
                200,
                {"model": model, "message": {"role": "assistant", "content": reply}, "done": True},
            )
        ),
    }


def free_port() -> int:
    """Return a port that nothing is listening on (used for refused-connection tests)."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]

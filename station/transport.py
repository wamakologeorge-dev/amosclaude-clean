"""Minimal JSON-over-HTTP helper built on urllib, with hard timeouts."""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from typing import Any, Mapping

from station import USER_AGENT

MAX_ERROR_BODY = 200


class TransportError(Exception):
    """The request never produced a usable HTTP response."""


class HttpError(Exception):
    """The server answered with a non-2xx status."""

    def __init__(self, status: int, body: str = "") -> None:
        super().__init__(f"HTTP {status}: {body[:MAX_ERROR_BODY]}" if body else f"HTTP {status}")
        self.status = status
        self.body = body[:MAX_ERROR_BODY]


def request_json(
    url: str,
    *,
    method: str = "GET",
    payload: Any | None = None,
    headers: Mapping[str, str] | None = None,
    timeout: float = 15.0,
) -> Any:
    """Perform a JSON request and return the decoded body (``None`` if empty)."""
    body = None
    if payload is not None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(url, data=body, method=method)
    request.add_header("Accept", "application/json")
    request.add_header("User-Agent", USER_AGENT)
    if body is not None:
        request.add_header("Content-Type", "application/json")
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as error:  # 4xx / 5xx
        detail = ""
        try:
            detail = error.read(2048).decode("utf-8", "replace")
        except Exception:  # pragma: no cover - body already consumed by urllib
            detail = ""
        raise HttpError(error.code, detail) from None
    except urllib.error.URLError as error:
        raise TransportError(str(error.reason)) from None
    except (TimeoutError, socket.timeout) as error:
        raise TransportError(f"timed out after {timeout}s: {error}") from None
    except OSError as error:
        raise TransportError(str(error)) from None
    if not raw.strip():
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise TransportError(f"response was not JSON: {error}") from None

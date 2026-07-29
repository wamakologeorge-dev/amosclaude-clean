"""Verify that GitHub Actions can authenticate to Ollama Cloud safely."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

DEFAULT_OLLAMA_URL = "https://ollama.com"


def _endpoint() -> str:
    return (os.getenv("OLLAMA_URL", "").strip() or DEFAULT_OLLAMA_URL).rstrip("/")


def _selected_model() -> str:
    return os.getenv("AMOSCLAUD_MODEL", "").strip()


def _write_summary(message: str) -> None:
    summary_path = os.getenv("GITHUB_STEP_SUMMARY", "").strip()
    if not summary_path:
        return
    with Path(summary_path).open("a", encoding="utf-8") as summary:
        summary.write(f"### Ollama connection\n\n{message}\n")


def verify_connection() -> int:
    """Check the authenticated model-list endpoint without exposing the API key."""

    api_key = os.getenv("OLLAMA_API_KEY", "").strip()
    if not api_key:
        message = "Skipped because `OLLAMA_API_KEY` is not configured for this run."
        print(message)
        _write_summary(message)
        return 0

    endpoint = _endpoint()
    parsed = urlparse(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        print("Ollama connection check failed: OLLAMA_URL is invalid.", file=sys.stderr)
        return 1

    request = Request(
        f"{endpoint}/api/tags",
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "Amosclaud-GitHub-Actions/1.0",
        },
    )

    try:
        with urlopen(request, timeout=20) as response:  # noqa: S310 - validated URL above
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        print(
            f"Ollama connection check failed with HTTP {exc.code}. Verify OLLAMA_API_KEY.",
            file=sys.stderr,
        )
        return 1
    except (URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        print(
            f"Ollama connection check failed: {type(exc).__name__}.",
            file=sys.stderr,
        )
        return 1

    models = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(models, list):
        print(
            "Ollama connection check failed: /api/tags returned an invalid response.",
            file=sys.stderr,
        )
        return 1

    names = {
        str(item.get("name") or item.get("model") or "").strip()
        for item in models
        if isinstance(item, dict)
    }
    names.discard("")
    selected_model = _selected_model()
    authority = f"{parsed.scheme}://{parsed.netloc}"
    message = f"Authenticated successfully to `{authority}`; {len(names)} model(s) are visible."
    if selected_model and selected_model not in names:
        message += (
            f" The configured model `{selected_model}` was not listed, so the agent will still "
            "verify it when making the first completion request."
        )

    print(message)
    _write_summary(message)
    return 0


def main() -> int:
    return verify_connection()


if __name__ == "__main__":
    raise SystemExit(main())

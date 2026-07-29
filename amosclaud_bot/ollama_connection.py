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
_TRUE_VALUES = {"1", "true", "yes", "on"}


def _endpoint() -> str:
    return (os.getenv("OLLAMA_URL", "").strip() or DEFAULT_OLLAMA_URL).rstrip("/")


def _selected_model() -> str:
    return os.getenv("AMOSCLAUD_MODEL", "").strip()


def _flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in _TRUE_VALUES


def _model_aliases(model: str) -> set[str]:
    if not model:
        return set()
    if model.endswith(":latest"):
        return {model, model.removesuffix(":latest")}
    return {model, f"{model}:latest"}


def _headers(api_key: str) -> dict[str, str]:
    return {
        "Accept": "application/json",
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": "Amosclaud-GitHub-Actions/1.0",
    }


def _write_summary(message: str) -> None:
    summary_path = os.getenv("GITHUB_STEP_SUMMARY", "").strip()
    if not summary_path:
        return
    with Path(summary_path).open("a", encoding="utf-8") as summary:
        summary.write(f"### Ollama connection\n\n{message}\n")


def _read_json(request: Request, *, timeout: int = 20) -> object:
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - URL is validated
        return json.loads(response.read().decode("utf-8"))


def _probe_completion(endpoint: str, api_key: str, model: str) -> bool:
    payload = json.dumps(
        {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": "You are the Amosclaud Ollama readiness probe.",
                },
                {
                    "role": "user",
                    "content": "Reply with exactly: AMOSCLAUD_OLLAMA_READY",
                },
            ],
            "temperature": 0,
            "max_tokens": 32,
            "stream": False,
        }
    ).encode("utf-8")
    request = Request(
        f"{endpoint}/v1/chat/completions",
        data=payload,
        method="POST",
        headers=_headers(api_key),
    )
    response = _read_json(request, timeout=60)
    if not isinstance(response, dict):
        return False
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        return False
    first = choices[0]
    if not isinstance(first, dict):
        return False
    message = first.get("message")
    if not isinstance(message, dict):
        return False
    content = str(message.get("content") or "")
    return "AMOSCLAUD_OLLAMA_READY" in content


def verify_connection() -> int:
    """Check Ollama authentication, model visibility, and optional completion."""

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

    request = Request(f"{endpoint}/api/tags", headers=_headers(api_key))
    try:
        payload = _read_json(request)
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
    selected_visible = bool(_model_aliases(selected_model) & names)
    authority = f"{parsed.scheme}://{parsed.netloc}"
    message = f"Authenticated successfully to `{authority}`; {len(names)} model(s) are visible."

    if selected_model and not selected_visible:
        if _flag("OLLAMA_REQUIRE_MODEL"):
            error = f"Configured Ollama model `{selected_model}` is not visible to this account."
            print(error, file=sys.stderr)
            _write_summary(error)
            return 1
        message += (
            f" The configured model `{selected_model}` was not listed, so the agent will still "
            "verify it when making the first completion request."
        )

    if _flag("OLLAMA_PROBE_COMPLETION"):
        if not selected_model:
            print(
                "Ollama completion check failed: AMOSCLAUD_MODEL is not configured.",
                file=sys.stderr,
            )
            return 1
        try:
            completion_ready = _probe_completion(endpoint, api_key, selected_model)
        except HTTPError as exc:
            print(
                f"Ollama completion check failed with HTTP {exc.code} for `{selected_model}`.",
                file=sys.stderr,
            )
            return 1
        except (URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            print(
                f"Ollama completion check failed: {type(exc).__name__}.",
                file=sys.stderr,
            )
            return 1
        if not completion_ready:
            print(
                f"Ollama completion check failed: `{selected_model}` did not return the probe token.",
                file=sys.stderr,
            )
            return 1
        message += f" Completion probe passed for `{selected_model}`."

    print(message)
    _write_summary(message)
    return 0


def main() -> int:
    return verify_connection()


if __name__ == "__main__":
    raise SystemExit(main())

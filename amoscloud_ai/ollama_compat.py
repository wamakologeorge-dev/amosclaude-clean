"""Normalize Ollama variables into Amosclaud's shared model contract.

The browser and user-facing clients never receive the Ollama credential. This
module only aliases server-side environment variables before an inference is
attempted.
"""

from __future__ import annotations

import os
from collections.abc import MutableMapping
from urllib.parse import urlsplit, urlunsplit

_OLLAMA_COMPLETIONS_PATH = "/v1/chat/completions"


def _normalise_ollama_url(value: str) -> tuple[str, str | None]:
    """Return a model base URL and an optional explicit completions path."""

    cleaned = value.strip().rstrip("/")
    if not cleaned:
        return "", None

    parsed = urlsplit(cleaned)
    if parsed.path.rstrip("/") != _OLLAMA_COMPLETIONS_PATH:
        return cleaned, None

    base = urlunsplit((parsed.scheme, parsed.netloc, "", parsed.query, parsed.fragment)).rstrip("/")
    return base, _OLLAMA_COMPLETIONS_PATH


def apply_ollama_environment(
    environ: MutableMapping[str, str] | None = None,
) -> dict[str, object]:
    """Map protected ``OLLAMA_*`` values to the canonical model variables.

    Existing ``AMOSCLAUD_*`` values always win. The returned report contains
    names and booleans only; secret values are never returned or logged.
    """

    target = environ if environ is not None else os.environ
    ollama_url = str(target.get("OLLAMA_URL") or "").strip()
    model_url, completions_path = _normalise_ollama_url(ollama_url)

    aliases = {
        "AMOSCLAUD_MODEL_URL": model_url,
        "AMOSCLAUD_MODEL_TOKEN": str(target.get("OLLAMA_API_KEY") or "").strip(),
        "AMOSCLAUD_MODEL": str(target.get("OLLAMA_MODEL") or "").strip(),
    }
    if completions_path:
        aliases["AMOSCLAUD_MODEL_COMPLETIONS_PATH"] = completions_path
    elif model_url and not str(target.get("AMOSCLAUD_MODEL_COMPLETIONS_PATH") or "").strip():
        aliases["AMOSCLAUD_MODEL_COMPLETIONS_PATH"] = _OLLAMA_COMPLETIONS_PATH

    applied: list[str] = []
    for name, value in aliases.items():
        if not value or str(target.get(name) or "").strip():
            continue
        target[name] = value
        applied.append(name)

    return {
        "ollama_configured": bool(model_url),
        "credential_configured": bool(str(target.get("AMOSCLAUD_MODEL_TOKEN") or "").strip()),
        "model": str(target.get("AMOSCLAUD_MODEL") or "").strip() or None,
        "applied": applied,
    }


__all__ = ["apply_ollama_environment"]

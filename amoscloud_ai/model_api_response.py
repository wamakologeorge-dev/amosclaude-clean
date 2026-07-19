"""Normalized model API response contract for every Amosclaud model backend.

This module converts OpenAI-compatible, Anthropic-style, model-network, and
first-party Amosclaud payloads into one truthful response shape. It never
invents model output and preserves provider errors for diagnostics.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ModelApiResponse:
    reply: str
    runtime: str
    status: str = "ready"
    provider: str = "amosclaud"
    model: str | None = None
    request_id: str | None = None
    finish_reason: str | None = None
    usage: dict[str, int] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict, repr=False)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == "ready" and bool(self.reply.strip()) and not self.error

    def to_dict(self, *, include_raw: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "reply": self.reply,
            "runtime": self.runtime,
            "status": self.status,
            "provider": self.provider,
            "model": self.model,
            "request_id": self.request_id,
            "finish_reason": self.finish_reason,
            "usage": dict(self.usage),
            "error": self.error,
            "ok": self.ok,
        }
        if include_raw:
            payload["raw"] = self.raw
        return payload


def _text_from_content(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts).strip()
    return ""


def normalize_model_api_response(
    payload: Any,
    *,
    runtime: str,
    provider: str = "amosclaud",
    model: str | None = None,
) -> ModelApiResponse:
    """Normalize a provider payload into the Amosclaud model response contract."""
    if not isinstance(payload, dict):
        return ModelApiResponse(
            reply="",
            runtime=runtime,
            provider=provider,
            model=model,
            status="degraded",
            error="Model API returned a non-object response",
        )

    reply = ""
    finish_reason = payload.get("finish_reason")

    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        choice = choices[0] if isinstance(choices[0], dict) else {}
        message = choice.get("message") if isinstance(choice, dict) else None
        if isinstance(message, dict):
            reply = _text_from_content(message.get("content"))
        if not reply and isinstance(choice, dict):
            reply = _text_from_content(choice.get("text"))
        finish_reason = choice.get("finish_reason") or finish_reason

    if not reply:
        reply = _text_from_content(payload.get("reply"))
    if not reply:
        reply = _text_from_content(payload.get("content"))
    if not reply:
        reply = _text_from_content(payload.get("output_text"))

    error_value = payload.get("error")
    error = None
    if isinstance(error_value, dict):
        error = str(error_value.get("message") or error_value.get("detail") or error_value)
    elif error_value:
        error = str(error_value)

    usage: dict[str, int] = {}
    raw_usage = payload.get("usage")
    if isinstance(raw_usage, dict):
        for key, value in raw_usage.items():
            if isinstance(value, int):
                usage[str(key)] = value

    resolved_model = str(payload.get("model") or model or "") or None
    request_id = str(payload.get("id") or payload.get("request_id") or "") or None
    status = "ready" if reply and not error else "degraded"
    if not reply and not error:
        error = "Model API returned an empty response"

    return ModelApiResponse(
        reply=reply,
        runtime=runtime,
        status=status,
        provider=provider,
        model=resolved_model,
        request_id=request_id,
        finish_reason=str(finish_reason) if finish_reason is not None else None,
        usage=usage,
        raw=payload,
        error=error,
    )

"""Production model station for Amosclaud Autonomous Cloud Agent.

The station exposes an OpenAI-compatible chat-completions endpoint and a truthful
health endpoint. It can connect to either an Ollama server or any OpenAI-compatible
upstream. It never reports ready until a real upstream model answers a probe.
"""

from __future__ import annotations

import os
import time
import uuid
from typing import Any, Literal

import httpx
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

STATION_NAME = os.getenv("AMOSCLAUD_STATION_NAME", "Amosclaud Model Station").strip()
BACKEND = os.getenv("AMOSCLAUD_MODEL_BACKEND", "ollama").strip().lower()
UPSTREAM_URL = os.getenv("AMOSCLAUD_MODEL_UPSTREAM_URL", "http://127.0.0.1:11434").strip().rstrip("/")
UPSTREAM_MODEL = os.getenv("AMOSCLAUD_MODEL_NAME", "qwen2.5-coder:7b").strip()
UPSTREAM_TOKEN = os.getenv("AMOSCLAUD_MODEL_UPSTREAM_TOKEN", "").strip()
STATION_TOKEN = os.getenv("AMOSCLAUD_MODEL_TOKEN", "").strip()
REQUEST_TIMEOUT = max(10.0, min(float(os.getenv("AMOSCLAUD_MODEL_TIMEOUT", "120")), 600.0))

app = FastAPI(title=STATION_NAME, version="1.0.0")


class Message(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str = Field(min_length=1, max_length=500_000)


class CompletionRequest(BaseModel):
    model: str | None = None
    messages: list[Message] = Field(min_length=1, max_length=200)
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    max_tokens: int = Field(default=1200, ge=1, le=32_000)


def _authorize(authorization: str | None) -> None:
    if not STATION_TOKEN:
        return
    if authorization != f"Bearer {STATION_TOKEN}":
        raise HTTPException(status_code=401, detail="Invalid model station token")


def _headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if UPSTREAM_TOKEN:
        headers["Authorization"] = f"Bearer {UPSTREAM_TOKEN}"
    return headers


def _ollama_completion(client: httpx.Client, body: CompletionRequest) -> str:
    response = client.post(
        f"{UPSTREAM_URL}/api/chat",
        headers=_headers(),
        json={
            "model": body.model or UPSTREAM_MODEL,
            "messages": [message.model_dump() for message in body.messages],
            "stream": False,
            "options": {"temperature": body.temperature, "num_predict": body.max_tokens},
        },
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    payload = response.json()
    reply = payload.get("message", {}).get("content")
    if not isinstance(reply, str) or not reply.strip():
        raise RuntimeError("Ollama returned no assistant content")
    return reply.strip()


def _openai_completion(client: httpx.Client, body: CompletionRequest) -> str:
    response = client.post(
        f"{UPSTREAM_URL}/v1/chat/completions",
        headers=_headers(),
        json={
            "model": body.model or UPSTREAM_MODEL,
            "messages": [message.model_dump() for message in body.messages],
            "temperature": body.temperature,
            "max_tokens": body.max_tokens,
            "stream": False,
        },
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    payload = response.json()
    reply = payload.get("choices", [{}])[0].get("message", {}).get("content")
    if not isinstance(reply, str) or not reply.strip():
        raise RuntimeError("OpenAI-compatible upstream returned no assistant content")
    return reply.strip()


def _complete(body: CompletionRequest) -> tuple[str, int]:
    started = time.monotonic()
    with httpx.Client() as client:
        if BACKEND == "ollama":
            reply = _ollama_completion(client, body)
        elif BACKEND in {"openai", "openai-compatible", "vllm", "llamacpp"}:
            reply = _openai_completion(client, body)
        else:
            raise RuntimeError(f"Unsupported AMOSCLAUD_MODEL_BACKEND: {BACKEND}")
    return reply, int((time.monotonic() - started) * 1000)


def _probe() -> dict[str, Any]:
    try:
        reply, latency_ms = _complete(
            CompletionRequest(
                model=UPSTREAM_MODEL,
                messages=[Message(role="user", content="Reply with READY only.")],
                temperature=0,
                max_tokens=8,
            )
        )
        ready = bool(reply.strip())
        return {
            "status": "ready" if ready else "not_ready",
            "ready": ready,
            "station": STATION_NAME,
            "backend": BACKEND,
            "model": UPSTREAM_MODEL,
            "checkpoint": True,
            "latency_ms": latency_ms,
        }
    except Exception as exc:
        return {
            "status": "not_ready",
            "ready": False,
            "station": STATION_NAME,
            "backend": BACKEND,
            "model": UPSTREAM_MODEL,
            "checkpoint": False,
            "detail": f"{type(exc).__name__}: {exc}",
        }


@app.get("/health")
def health(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    _authorize(authorization)
    return _probe()


@app.post("/v1/chat/completions")
def chat_completions(
    body: CompletionRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _authorize(authorization)
    try:
        reply, latency_ms = _complete(body)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail=f"Upstream model rejected inference ({exc.response.status_code})") from exc
    except (httpx.HTTPError, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail=f"Model station unavailable: {type(exc).__name__}") from exc
    model_name = body.model or UPSTREAM_MODEL
    return {
        "id": "chatcmpl-" + uuid.uuid4().hex,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model_name,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": reply}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "station": {"name": STATION_NAME, "backend": BACKEND, "latency_ms": latency_ms},
    }

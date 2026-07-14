"""OpenAI-compatible HTTP service for the folder-native Amosclaud model."""

from __future__ import annotations

import os
import time
import uuid

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from amosclaud_model import __version__
from amosclaud_model.config import model_root
from amosclaud_model.model import FolderLanguageModel, tokenize
from amosclaud_model.workspace import initialize


class Message(BaseModel):
    role: str
    content: str


class CompletionRequest(BaseModel):
    model: str = "amosclaud-folder-v1"
    messages: list[Message] = Field(min_length=1)
    temperature: float = Field(default=0.35, ge=0, le=2)
    max_tokens: int = Field(default=512, ge=1, le=4096)


def _authorize(authorization: str | None = Header(default=None)) -> None:
    expected = os.getenv("AMOSCLAUD_MODEL_TOKEN", "").strip()
    if expected and authorization != f"Bearer {expected}":
        raise HTTPException(status_code=401, detail="Invalid model service credential")


def create_app() -> FastAPI:
    root = model_root()
    initialize(root)
    model = FolderLanguageModel(root)
    app = FastAPI(title="Amosclaud Native Model", version=__version__)

    @app.get("/health")
    def health() -> dict:
        return {
            "status": "ready" if model.checkpoint_path.exists() else "needs_training",
            "model": model.config.name,
            "checkpoint": model.checkpoint_path.exists(),
            "key_required": bool(os.getenv("AMOSCLAUD_MODEL_TOKEN", "").strip()),
        }

    @app.get("/v1/models", dependencies=[Depends(_authorize)])
    def models() -> dict:
        return {
            "object": "list",
            "data": [{"id": model.config.name, "object": "model", "owned_by": "amosclaud"}],
        }

    @app.post("/v1/chat/completions", dependencies=[Depends(_authorize)])
    def complete(body: CompletionRequest) -> dict:
        if not model.checkpoint_path.exists():
            raise HTTPException(
                status_code=503, detail="Model needs training. Run `amosclaud-model train`."
            )
        prompt = (
            "\n".join(f"<{message.role}>\n{message.content}" for message in body.messages)
            + "\n<assistant>\n"
        )
        started = time.monotonic()
        reply = model.generate(prompt, body.max_tokens, body.temperature)
        prompt_tokens = len(tokenize(prompt))
        completion_tokens = len(tokenize(reply))
        return {
            "id": "chatcmpl_" + uuid.uuid4().hex,
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model.config.name,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": reply},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
            "amosclaud": {
                "runtime": "folder-native",
                "latency_ms": round((time.monotonic() - started) * 1000, 2),
            },
        }

    return app


app = create_app()

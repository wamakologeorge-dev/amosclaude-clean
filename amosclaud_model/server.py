"""OpenAI-compatible HTTP service for the folder-native Amosclaud model."""

from __future__ import annotations

import json
import os
import secrets
import time
import uuid

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from amosclaud_model import __version__
from amosclaud_model.config import model_root
from amosclaud_model.model import FolderLanguageModel, tokenize
from amosclaud_model.service_log import ModelServiceLog
from amosclaud_model.training_service import TrainingService, audit_dataset_licenses
from amosclaud_model.workspace import initialize


class Message(BaseModel):
    role: str
    content: str


class CompletionRequest(BaseModel):
    model: str = "amosclaud-folder-v1"
    messages: list[Message] = Field(min_length=1)
    temperature: float = Field(default=0.35, ge=0, le=2)
    max_tokens: int = Field(default=512, ge=1, le=4096)


class TrainingRequest(BaseModel):
    operation: str = Field(default="train", pattern="^(train|evaluate)$")


def _authorize(
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> None:
    expected = [
        value
        for value in (
            os.getenv("AMOSCLAUD_MODEL_TOKEN", "").strip(),
            os.getenv("AMOSCLAUD_API_KEY", "").strip(),
        )
        if value
    ]
    if not expected:
        return
    bearer = authorization.removeprefix("Bearer ").strip() if authorization else ""
    supplied = [value for value in (bearer, (x_api_key or "").strip()) if value]
    if not any(
        secrets.compare_digest(candidate, accepted)
        for candidate in supplied
        for accepted in expected
    ):
        raise HTTPException(status_code=401, detail="Invalid Amosclaud model credential")


def create_app() -> FastAPI:
    root = model_root()
    initialize(root)
    model = FolderLanguageModel(root)
    service_log = ModelServiceLog(root)
    training = TrainingService(root)
    app = FastAPI(title="Amosclaud Native Model", version=__version__)

    @app.get("/health")
    def health() -> dict:
        return {
            "status": "ready" if model.checkpoint_path.exists() else "needs_training",
            "model": model.config.name,
            "checkpoint": model.checkpoint_path.exists(),
            "key_required": bool(
                os.getenv("AMOSCLAUD_MODEL_TOKEN", "").strip()
                or os.getenv("AMOSCLAUD_API_KEY", "").strip()
            ),
            "amosclaud_api_key_supported": True,
        }

    @app.get("/v1/models", dependencies=[Depends(_authorize)])
    def models() -> dict:
        return {
            "object": "list",
            "data": [{"id": model.config.name, "object": "model", "owned_by": "amosclaud"}],
        }

    @app.post("/v1/chat/completions", dependencies=[Depends(_authorize)])
    def complete(body: CompletionRequest) -> dict:
        request_id = "chatcmpl_" + uuid.uuid4().hex
        if not model.checkpoint_path.exists():
            raise HTTPException(
                status_code=503, detail="Model needs training. Run `amosclaud-model train`."
            )
        prompt = (
            "\n".join(f"<{message.role}>\n{message.content}" for message in body.messages)
            + "\n<assistant>\n"
        )
        started = time.monotonic()
        try:
            reply = model.generate(prompt, body.max_tokens, body.temperature)
            prompt_tokens = len(tokenize(prompt))
            completion_tokens = len(tokenize(reply))
            latency_ms = round((time.monotonic() - started) * 1000, 2)
            checkpoint = json.loads(model.checkpoint_path.read_text(encoding="utf-8")).get(
                "checkpoint_id", "unknown"
            )
            service_log.append(
                "inference.completed",
                request_id=request_id,
                model=model.config.name,
                checkpoint_id=checkpoint,
                prompt_fingerprint=service_log.fingerprint(prompt),
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
                latency_ms=latency_ms,
                outcome="success",
            )
        except Exception as error:
            service_log.append(
                "inference.failed",
                request_id=request_id,
                model=model.config.name,
                prompt_fingerprint=service_log.fingerprint(prompt),
                latency_ms=round((time.monotonic() - started) * 1000, 2),
                outcome="error",
                error_type=type(error).__name__,
            )
            raise
        return {
            "id": request_id,
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
                "latency_ms": latency_ms,
            },
        }

    @app.get("/v1/logs", dependencies=[Depends(_authorize)])
    def logs(limit: int = 100, event: str | None = None) -> dict:
        return {"object": "list", "data": service_log.events(limit, event)}

    @app.get("/v1/logs/summary", dependencies=[Depends(_authorize)])
    def log_summary() -> dict:
        return service_log.summary()

    @app.get("/v1/logs/verify", dependencies=[Depends(_authorize)])
    def verify_logs() -> dict:
        return service_log.verify()

    @app.get("/v1/training/licenses", dependencies=[Depends(_authorize)])
    def training_licenses() -> dict:
        return audit_dataset_licenses(root)

    @app.post("/v1/training/jobs", status_code=202, dependencies=[Depends(_authorize)])
    def create_training_job(body: TrainingRequest) -> dict:
        try:
            return training.submit(body.operation)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except RuntimeError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.get("/v1/training/jobs", dependencies=[Depends(_authorize)])
    def training_jobs(limit: int = 25) -> dict:
        return {"object": "list", "data": training.list(limit)}

    @app.get("/v1/training/jobs/{job_id}", dependencies=[Depends(_authorize)])
    def training_job(job_id: str) -> dict:
        job = training.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Training job not found")
        return job

    return app


app = create_app()

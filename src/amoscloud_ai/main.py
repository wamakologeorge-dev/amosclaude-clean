"""Amosclaud-AI application entry point.

This module exposes a FastAPI app that serves the web UI and the offline-capable
AI endpoints used by the browser and Android clients.
"""

import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from src.amoscloud_ai.builder import BuilderService
from src.amoscloud_ai.config import settings
from src.amoscloud_ai.logger import log
from src.amoscloud_ai.models import BuildResult, BuildStatus

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)

app = FastAPI(
    title="Amoscloud AI",
    description="Offline-capable Amosclaud-AI server for chat, build plans, and web UI hosting.",
    version="1.0.0",
)

_WEB_DIR = Path(__file__).resolve().parents[2] / "web"
builder_service = BuilderService()
_MAX_BYTES = settings.max_upload_size_mb * 1024 * 1024


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    """Serve the main web UI."""
    return HTMLResponse((_WEB_DIR / "index.html").read_text(encoding="utf-8"))


@app.get("/styles.css")
async def styles() -> FileResponse:
    return FileResponse(_WEB_DIR / "styles.css")


@app.get("/app.js")
async def app_js() -> FileResponse:
    return FileResponse(_WEB_DIR / "app.js")


@app.get("/health")
async def health() -> dict:
    """Health check used by Docker and load balancers."""
    return {"status": "healthy", "service": "amosclaud-ai", "version": "1.0.0"}


@app.post("/build/photo", response_model=BuildResult)
async def build_from_photo(
    photo: UploadFile = File(..., description="Image file (PNG, JPEG, GIF, WebP)"),
    instructions: str = Form(default="", description="Optional additional instructions"),
) -> BuildResult:
    """Build from an uploaded image or screenshot."""
    content_type = photo.content_type or ""
    if not content_type.startswith("image/"):
        return BuildResult(
            status=BuildStatus.FAILED,
            mode="photo",
            summary="Upload rejected.",
            error=f"File must be an image, got: {content_type}",
        )

    raw = await photo.read()
    if len(raw) > _MAX_BYTES:
        return BuildResult(
            status=BuildStatus.FAILED,
            mode="photo",
            summary="Upload rejected.",
            error=f"File too large (max {settings.max_upload_size_mb} MB).",
        )

    log.info("Received photo upload: %s (%d bytes)", photo.filename, len(raw))
    return builder_service.build_from_photo(
        image_bytes=raw,
        filename=photo.filename or "upload.png",
        extra_instructions=instructions or None,
    )


@app.post("/build/instructions", response_model=BuildResult)
async def build_from_instructions(
    instructions: str = Form(..., description="What you want to build"),
    context: str = Form(default="", description="Optional project context"),
) -> BuildResult:
    """Build from plain-text instructions."""
    if not instructions.strip():
        return BuildResult(
            status=BuildStatus.FAILED,
            mode="instructions",
            summary="No instructions provided.",
            error="Instructions field must not be empty.",
        )

    log.info("Received instructions build request")
    return builder_service.build_from_instructions(
        instructions=instructions,
        context=context or None,
    )


_conversations: dict[str, list[dict]] = {}


@app.post("/api/chat")
async def chat(payload: ChatRequest) -> dict:
    """Handle the browser/Android chat requests with an offline-safe fallback."""
    session_id = payload.session_id or _new_session_id()
    message = payload.message.strip()
    if not message:
        return {"error": "message is required"}

    history = _conversations.setdefault(session_id, [])
    history.append({"role": "user", "content": message, "timestamp": _now()})
    reply = _generate_reply(message, history)
    history.append({"role": "assistant", "content": reply, "timestamp": _now()})

    return {"reply": reply, "session_id": session_id, "timestamp": _now()}


@app.get("/api/chat/history/{session_id}")
async def chat_history(session_id: str) -> dict:
    return {"session_id": session_id, "history": _conversations.get(session_id, [])}


@app.delete("/api/chat/history/{session_id}")
async def clear_history(session_id: str) -> dict:
    _conversations.pop(session_id, None)
    return {"session_id": session_id, "cleared": True}


@app.get("/api/capabilities")
async def capabilities() -> dict:
    return {
        "name": "Amosclaud-AI",
        "version": "1.0.0",
        "capabilities": [
            "ci_cd_automation",
            "code_analysis",
            "deployment",
            "database_management",
            "git_operations",
            "intelligent_chat",
        ],
        "description": "Professional CI/CD & Deployment Automation AI",
    }


_GREETINGS = {"hi", "hello", "hey", "greetings", "howdy"}
_KEYWORD_REPLIES: list[tuple[list[str], str]] = [
    (["deploy", "deployment", "release"], "I can handle deployments for you! Use the CI/CD pipeline or tell me the target environment (dev / staging / production) and I'll kick off the deployment workflow."),
    (["test", "tests", "testing", "pytest"], "I can run your test suite automatically. Trigger integration tests with `pytest tests/` or let me orchestrate the full CI pipeline including lint → test → build → deploy."),
    (["database", "db", "migrate", "migration", "postgres"], "Database operations are fully automated: migrations, backups, and optimisation. Tell me which database action you need and I'll execute it safely."),
    (["git", "commit", "branch", "push", "pull", "merge"], "I manage Git operations end-to-end: branching, committing, merging, and pushing. What repo action do you need?"),
    (["build", "compile", "docker", "container", "image"], "I can build Docker images, run `docker-compose up`, and manage the full container lifecycle. What would you like to build?"),
    (["code", "analyze", "review", "lint", "refactor"], "Code analysis is one of my core capabilities. I can review files, suggest refactors, run linters, and detect issues automatically."),
    (["log", "logs", "error", "debug", "trace"], "I aggregate logs from all services in real-time. Share the error message or service name and I'll diagnose the issue."),
    (["help", "what can you do", "capabilities", "features"], "I'm Amosclaud-AI — your autonomous CI/CD assistant! I can:\n• Deploy apps to any environment\n• Run automated tests\n• Manage databases\n• Analyse and edit code\n• Handle Git operations\n• Monitor logs and errors\n\nJust tell me what you need!"),
    (["browser", "search", "web", "url", "open"], "Use the built-in browser tab to navigate any URL. I can also help you search for documentation or resources — what are you looking for?"),
]


def _new_session_id() -> str:
    return str(uuid.uuid4())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _rule_based_reply(message: str) -> str:
    lower = message.lower().strip(" ?!.,")
    if lower in _GREETINGS:
        return "Hello! I'm Amosclaud-AI 🤖 — your intelligent CI/CD automation assistant. How can I help you today?"

    for keywords, reply in _KEYWORD_REPLIES:
        if any(keyword in lower for keyword in keywords):
            return reply

    return (
        f'I received your message: "{message}"\n\n'
        "I'm Amosclaud-AI, specialising in CI/CD automation, deployments, code analysis, "
        "and DevOps workflows. Could you give me more details so I can assist you better?"
    )


def _generate_reply(message: str, history: list[dict]) -> str:
    return _rule_based_reply(message)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.amoscloud_ai.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.environment == "development",
        log_level=settings.log_level.lower(),
    )

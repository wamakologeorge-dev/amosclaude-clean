"""
Amoscloud AI application entry point.
Starts the FastAPI server that serves the web UI, build endpoints and chat API.
"""
import os
import logging
from pathlib import Path

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from src.amoscloud_ai.api import chat_api
from src.amoscloud_ai.builder import BuilderService
from src.amoscloud_ai.config import settings
from src.amoscloud_ai.logger import log
from src.amoscloud_ai.models import BuildResult, BuildStatus

# App setup

app = FastAPI(
    title="Amoscloud AI",
    description="Build projects from photo uploads or text instructions.",
    version="1.0.0",
)

# /repo/src/amoscloud_ai/main.py -> /repo
_REPO_ROOT = Path(__file__).resolve().parents[2]
_WEB_DIR = _REPO_ROOT / "web"
builder_service = BuilderService()

_MAX_BYTES = settings.max_upload_size_mb * 1024 * 1024


# Routes

@app.get("/")
async def index() -> FileResponse:
    """Serve the main web UI."""
    return FileResponse(_WEB_DIR / "index.html")


@app.get("/styles.css")
async def styles_css() -> FileResponse:
    """Serve the web stylesheet."""
    return FileResponse(_WEB_DIR / "styles.css")


@app.get("/app.js")
async def app_js() -> FileResponse:
    """Serve the web client script."""
    return FileResponse(_WEB_DIR / "app.js")


@app.post("/build/photo", response_model=BuildResult)
async def build_from_photo(
    photo: UploadFile = File(..., description="Image file (PNG, JPEG, GIF, WebP)"),
    instructions: str = Form(default="", description="Optional additional instructions"),
) -> BuildResult:
    """Build from an uploaded photo/screenshot."""
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


@app.get("/health")
async def health() -> dict:
    """Health check used by Docker and load balancers."""
    return {"status": "healthy", "service": "amoscloud-ai", "version": "1.0.0"}


@app.post("/api/chat")
async def chat(request: Request) -> JSONResponse:
    """Handle chat messages for the web and Android clients."""
    try:
        data = await request.json()
    except Exception as exc:
        log.warning("Failed to parse chat JSON payload: %s", exc)
        return JSONResponse(status_code=400, content={"error": "invalid JSON payload"})

    message = str(data.get("message") or "").strip()
    if not message:
        return JSONResponse(status_code=400, content={"error": "message is required"})

    session_id = data.get("session_id") or chat_api.create_session_id()
    history = chat_api.get_or_create_history(session_id)
    chat_api.append_turn(session_id, "user", message)

    reply = chat_api.generate_reply(message, history)
    chat_api.append_turn(session_id, "assistant", reply)

    return JSONResponse(
        content={
            "reply": reply,
            "session_id": session_id,
            "timestamp": chat_api.get_timestamp(),
        }
    )


@app.get("/api/chat/history/{session_id}")
async def chat_history(session_id: str) -> JSONResponse:
    """Return conversation history for a session."""
    history = chat_api.get_history(session_id)
    return JSONResponse(content={"session_id": session_id, "history": history})


@app.delete("/api/chat/history/{session_id}")
async def clear_history(session_id: str) -> JSONResponse:
    """Clear conversation history for a session."""
    chat_api.clear_history(session_id)
    return JSONResponse(content={"session_id": session_id, "cleared": True})


@app.get("/api/capabilities")
async def capabilities() -> JSONResponse:
    """Return the AI capabilities exposed by this backend."""
    return JSONResponse(
        content={
            "name": "Amoscloud AI",
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
    )


# Dev server entry point

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.amoscloud_ai.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.environment == "development",
        log_level=settings.log_level.lower(),
    )

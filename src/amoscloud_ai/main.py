"""Amoscloud AI application entry point.

Provides the FastAPI web application used by the build assistant UI and build endpoints.
"""

import logging
import os
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from src.amoscloud_ai.builder import BuilderService
from src.amoscloud_ai.config import settings
from src.amoscloud_ai.logger import log
from src.amoscloud_ai.models import BuildResult, BuildStatus

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Amoscloud AI",
        description="Build projects from photo uploads or text instructions.",
        version="1.0.0",
    )

    templates_dir = Path(__file__).parent / "templates"
    templates = Jinja2Templates(directory=str(templates_dir))
    builder_service = BuilderService()

    max_bytes = settings.max_upload_size_mb * 1024 * 1024

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        """Serve the main web UI."""
        return templates.TemplateResponse(request=request, name="index.html")

    @app.post("/build/photo", response_model=BuildResult)
    async def build_from_photo(
        photo: UploadFile = File(..., description="Image file (PNG, JPEG, GIF, WebP)"),
        instructions: str = Form(default="", description="Optional additional instructions"),
    ) -> BuildResult:
        """Build from an uploaded photo or screenshot."""
        content_type = photo.content_type or ""
        if not content_type.startswith("image/"):
            return BuildResult(
                status=BuildStatus.FAILED,
                mode="photo",
                summary="Upload rejected.",
                error=f"File must be an image, got: {content_type}",
            )

        raw = await photo.read()
        if len(raw) > max_bytes:
            return BuildResult(
                status=BuildStatus.FAILED,
                mode="photo",
                summary="Upload rejected.",
                error=f"File too large (max {settings.max_upload_size_mb} MB).",
            )

        log.info(f"Received photo upload: {photo.filename} ({len(raw)} bytes)")
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
        return {"status": "healthy", "service": "amoscloud-ai"}

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.amoscloud_ai.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.environment == "development",
        log_level=settings.log_level.lower(),
    )

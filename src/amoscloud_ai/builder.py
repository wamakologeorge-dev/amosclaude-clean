"""
Builder service – processes build requests from photo uploads or text instructions
using the Claude API (Anthropic).
"""

import base64
import mimetypes
from typing import Optional

import anthropic

from src.amoscloud_ai.config import settings
from src.amoscloud_ai.logger import log
from src.amoscloud_ai.models import BuildMode, BuildResult, BuildStatus

# System prompt shared by both modes
_SYSTEM_PROMPT = """\
You are Amoscloud AI, an expert software architect and CI/CD automation engineer.
Your task is to analyse the user's input and produce:
1. A concise **project plan** (bullet-list of components/steps).
2. A concrete **implementation outline** with the key files, configurations, or
   commands needed to build and deploy the described project.

Be specific, actionable, and ready for a developer to act on immediately.
Format your response in clear Markdown with two sections:
## Project Plan
## Implementation Outline
"""


class BuilderService:
    """Handle AI-powered build requests from photos or instructions."""

    def __init__(self) -> None:
        self._client: Optional[anthropic.Anthropic] = None

    def _get_client(self) -> anthropic.Anthropic:
        if self._client is None:
            self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        return self._client

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def build_from_instructions(
        self,
        instructions: str,
        context: Optional[str] = None,
    ) -> BuildResult:
        """Generate a build plan from plain-text instructions."""
        log.info("Processing build request via instructions")
        try:
            user_content = instructions
            if context:
                user_content = f"**Context:**\n{context}\n\n**Instructions:**\n{instructions}"

            response = self._get_client().messages.create(
                model=settings.claude_model,
                max_tokens=2048,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_content}],
            )

            result_text = response.content[0].text
            log.info("Instructions build completed successfully")
            return BuildResult(
                status=BuildStatus.COMPLETED,
                mode=BuildMode.INSTRUCTIONS,
                summary="Build plan generated from instructions.",
                generated_plan=result_text,
            )

        except Exception as exc:
            log.error(f"Instructions build failed: {exc}")
            return BuildResult(
                status=BuildStatus.FAILED,
                mode=BuildMode.INSTRUCTIONS,
                summary="Build failed.",
                error=str(exc),
            )

    def build_from_photo(
        self,
        image_bytes: bytes,
        filename: str,
        extra_instructions: Optional[str] = None,
    ) -> BuildResult:
        """Analyse an uploaded image and generate a build plan."""
        log.info(f"Processing build request via photo upload: {filename}")
        try:
            # Detect media type
            mime_type, _ = mimetypes.guess_type(filename)
            if mime_type not in {"image/jpeg", "image/png", "image/gif", "image/webp"}:
                mime_type = "image/png"  # safe fallback

            image_data = base64.standard_b64encode(image_bytes).decode("utf-8")

            user_message: list = [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": mime_type,
                        "data": image_data,
                    },
                },
                {
                    "type": "text",
                    "text": (
                        "Please analyse this image and generate a complete build plan "
                        "for the project or application shown.\n"
                        + (f"\nAdditional instructions: {extra_instructions}" if extra_instructions else "")
                    ),
                },
            ]

            response = self._get_client().messages.create(
                model=settings.claude_model,
                max_tokens=2048,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
            )

            result_text = response.content[0].text
            log.info("Photo build completed successfully")
            return BuildResult(
                status=BuildStatus.COMPLETED,
                mode=BuildMode.PHOTO,
                summary="Build plan generated from uploaded photo.",
                generated_plan=result_text,
            )

        except Exception as exc:
            log.error(f"Photo build failed: {exc}")
            return BuildResult(
                status=BuildStatus.FAILED,
                mode=BuildMode.PHOTO,
                summary="Build failed.",
                error=str(exc),
            )

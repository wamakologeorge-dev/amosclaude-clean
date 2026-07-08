"""
Builder service – processes build requests from photo uploads or text instructions
using the Claude API (Anthropic) when available and falls back to a local plan offline.
"""

import base64
import mimetypes
from typing import Any, Optional

from src.amoscloud_ai.config import settings
from src.amoscloud_ai.logger import log
from src.amoscloud_ai.models import BuildMode, BuildResult, BuildStatus

# System prompt shared by both modes
_SYSTEM_PROMPT = """\
You are Amoscloud AI, an expert software architect and CI/CD automation engineer.
Your task is to analyze the user's input and produce:
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
        self._client: Optional[Any] = None

    def _get_client(self) -> Optional[Any]:
        if self._client is None and settings.anthropic_api_key:
            try:
                # Import the Anthropic SDK lazily so the app can still run offline.
                import anthropic  # type: ignore[import-not-found]
            except ImportError:
                log.info("Anthropic package is not installed; using offline build plan fallback")
                return None

            self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        return self._client

    def _offline_plan(self, mode: BuildMode, source: str) -> str:
        safe_source = " ".join(str(source).split())[:240]

        if mode == BuildMode.PHOTO:
            return (
                "## Project Plan\n"
                "- Inspect the uploaded screen or image and identify the key UI and workflow elements.\n"
                "- Turn that into a simple architecture with a clear entry point and state model.\n"
                "- Prepare the local files, assets, and test commands needed to implement the experience.\n\n"
                "## Implementation Outline\n"
                "- Create a minimal app shell with a single page or route and a clear source folder structure.\n"
                "- Add basic styling, data handling, and any API integration points required by the design.\n"
                "- Validate the result locally with the project’s build and test commands before deployment."
            )

        return (
            "## Project Plan\n"
            f"- Break the request into a small, testable implementation plan for: {safe_source}.\n"
            "- Create the core files, configuration, and dependency list needed for the first working version.\n"
            "- Validate the build locally before you deploy or share it.\n\n"
            "## Implementation Outline\n"
            "- Start with the smallest working scaffold and a clear entry point.\n"
            "- Add supporting modules, tests, and any deployment or environment configuration needed.\n"
            "- Run the local build and test commands and capture the results for the next iteration."
        )

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

            client = self._get_client()
            if client is None:
                log.info("No Anthropic client available, using offline fallback plan")
                return BuildResult(
                    status=BuildStatus.COMPLETED,
                    mode=BuildMode.INSTRUCTIONS,
                    summary="Offline fallback plan generated locally.",
                    generated_plan=self._offline_plan(BuildMode.INSTRUCTIONS, user_content),
                )

            response = client.messages.create(
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
            log.error("Instructions build failed, using offline fallback: %s", exc)
            return BuildResult(
                status=BuildStatus.COMPLETED,
                mode=BuildMode.INSTRUCTIONS,
                summary="Offline fallback plan generated locally after a remote AI error.",
                generated_plan=self._offline_plan(BuildMode.INSTRUCTIONS, instructions),
            )

    def build_from_photo(
        self,
        image_bytes: bytes,
        filename: str,
        extra_instructions: Optional[str] = None,
    ) -> BuildResult:
        """Analyse an uploaded image and generate a build plan."""
        log.info("Processing build request via photo upload: %s", filename)
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
                        "Please analyze this image and generate a complete build plan "
                        "for the project or application shown.\n"
                        + (f"\nAdditional instructions: {extra_instructions}" if extra_instructions else "")
                    ),
                },
            ]

            client = self._get_client()
            if client is None:
                log.info("No Anthropic client available, using offline fallback plan")
                return BuildResult(
                    status=BuildStatus.COMPLETED,
                    mode=BuildMode.PHOTO,
                    summary="Offline fallback plan generated locally.",
                    generated_plan=self._offline_plan(BuildMode.PHOTO, filename),
                )

            response = client.messages.create(
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
            log.error("Photo build failed, using offline fallback: %s", exc)
            return BuildResult(
                status=BuildStatus.COMPLETED,
                mode=BuildMode.PHOTO,
                summary="Offline fallback plan generated locally after a remote AI error.",
                generated_plan=self._offline_plan(BuildMode.PHOTO, filename),
            )

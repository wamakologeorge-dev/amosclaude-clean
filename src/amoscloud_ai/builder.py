"""
Builder service – processes build requests from photo uploads or text instructions
using the Claude API (Anthropic) when available, otherwise using a local fallback.
"""

import base64
import mimetypes
from typing import Optional

try:
   import anthropic  # type: ignore
except ImportError:  # pragma: no cover - exercised in offline environments
   anthropic = None

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
       self._client = None

   def _get_client(self):
       if anthropic is None:
           return None
       if self._client is None:
           self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
       return self._client

   def _offline_plan(self, mode: BuildMode, instructions: Optional[str] = None, context: Optional[str] = None) -> BuildResult:
       prompt = instructions or ""
       if context:
           prompt = f"{context}\n\n{prompt}".strip()
       summary = "Offline build plan generated locally."
       generated_plan = f"## Project Plan\n- Inspect the requested application requirements\n- Create the core project structure\n- Implement the main features locally\n\n## Implementation Outline\n- Add the required files and modules\n- Wire up the server and UI entry points\n- Validate the build with the local test suite"
       if prompt:
           generated_plan += f"\n\nRequested input: {prompt}"
       return BuildResult(
           status=BuildStatus.COMPLETED,
           mode=mode,
           summary=summary,
           generated_plan=generated_plan,
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
       client = self._get_client()
       if client is None:
           log.info("Anthropic client unavailable; returning offline build plan")
           return self._offline_plan(BuildMode.INSTRUCTIONS, instructions, context)

       try:
           user_content = instructions
           if context:
               user_content = f"**Context:**\n{context}\n\n**Instructions:**\n{instructions}"

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
           log.error("Instructions build failed: %s", exc)
           return self._offline_plan(BuildMode.INSTRUCTIONS, instructions, context)

   def build_from_photo(
       self,
       image_bytes: bytes,
       filename: str,
       extra_instructions: Optional[str] = None,
   ) -> BuildResult:
       """Analyse an uploaded image and generate a build plan."""
       log.info("Processing build request via photo upload: %s", filename)
       client = self._get_client()
       if client is None:
           log.info("Anthropic client unavailable; returning offline build plan")
           return self._offline_plan(BuildMode.PHOTO, extra_instructions or filename)

       try:
           mime_type, _ = mimetypes.guess_type(filename)
           if mime_type not in {"image/jpeg", "image/png", "image/gif", "image/webp"}:
               mime_type = "image/png"

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
           log.error("Photo build failed: %s", exc)
           return self._offline_plan(BuildMode.PHOTO, extra_instructions or filename)

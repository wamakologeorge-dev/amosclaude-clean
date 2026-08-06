"""Public source and documentation catalog for Amosclaud.

The repository source, license, and documentation remain public under the
published license. Official hosted tools, packaged downloads, remote MCP,
editor cloud actions, and managed execution require verified organization
support time.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, RedirectResponse

router = APIRouter(tags=["public-developer-tools"])
REPOSITORY = "https://github.com/wamakologeorge-dev/amosclaude-clean"
WEB_ROOT = Path(__file__).resolve().parents[3] / "web"


@router.get("/api/v1/open-source/tools")
def open_source_tools(request: Request) -> dict:
    """Return the public-source boundary and paid official-tool policy."""

    origin = str(request.base_url).rstrip("/")
    return {
        "access": "public_source_only",
        "account_required": False,
        "license_url": f"{REPOSITORY}/blob/main/LICENSE",
        "source_repository": REPOSITORY,
        "public_resources": [
            {
                "id": "source",
                "name": "Amosclaud source code",
                "kind": "source",
                "url": REPOSITORY,
                "account_required": False,
            },
            {
                "id": "documentation",
                "name": "Amosclaud documentation",
                "kind": "documentation",
                "url": f"{REPOSITORY}/tree/main/docs",
                "account_required": False,
            },
            {
                "id": "license",
                "name": "Published software license",
                "kind": "license",
                "url": f"{REPOSITORY}/blob/main/LICENSE",
                "account_required": False,
            },
        ],
        "official_tools": {
            "account_required": True,
            "verified_support_time_required": True,
            "examples": [
                "official Linux, Windows, and macOS packages",
                "hosted Autonomous engineering runs",
                "managed cloud workers and verification",
                "hosted model and OpenAI-compatible API usage",
                "managed repositories, operation buckets, and artifacts",
                "VS Code cloud actions and remote MCP tools",
            ],
            "support_url": f"{origin}/organization-support",
            "login_url": f"{origin}/login",
        },
        "open_source_boundary": (
            "Public source can be inspected and modified under the repository license. "
            "The official Amosclaud hosted control plane enforces verified support time."
        ),
    }


@router.get("/developer-tools", include_in_schema=False)
def developer_tools_page() -> FileResponse:
    """Serve the public source and official-tool policy page."""

    return FileResponse(WEB_ROOT / "developer-tools.html")


@router.get("/open-source", include_in_schema=False)
def open_source_alias() -> RedirectResponse:
    return RedirectResponse("/developer-tools", status_code=307)


__all__ = ["router", "open_source_tools"]

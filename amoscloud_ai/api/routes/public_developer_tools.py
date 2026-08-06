"""Public catalog for Amosclaud open-source developer tools.

This router deliberately has no session, API-key, wallet, or subscription
dependency. Developers can discover and download the source, local server, VS
Code client, CLI, and MCP integration even when hosted account access is down.
Hosted Autonomous execution remains behind the existing account and credit
boundaries.
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
    """Return the no-login developer-tool catalog and the paid-service boundary."""

    origin = str(request.base_url).rstrip("/")
    return {
        "access": "public",
        "account_required": False,
        "license_url": f"{REPOSITORY}/blob/main/LICENSE",
        "source_repository": REPOSITORY,
        "tools": [
            {
                "id": "source",
                "name": "Amosclaud source code",
                "kind": "source",
                "url": REPOSITORY,
                "account_required": False,
            },
            {
                "id": "linux-server",
                "name": "Linux local server",
                "kind": "download",
                "url": f"{origin}/api/v1/downloads/linux",
                "account_required": False,
            },
            {
                "id": "windows-server",
                "name": "Windows local server",
                "kind": "download",
                "url": f"{origin}/api/v1/downloads/windows",
                "account_required": False,
            },
            {
                "id": "macos-server",
                "name": "macOS local server",
                "kind": "download",
                "url": f"{origin}/api/v1/downloads/macos",
                "account_required": False,
            },
            {
                "id": "vscode",
                "name": "Amosclaud VS Code client",
                "kind": "editor",
                "url": f"{REPOSITORY}/tree/main/clients/vscode-amosclaud",
                "documentation_url": (
                    f"{REPOSITORY}/blob/main/docs/VSCODE_NATIVE_AGENT_AND_REMOTE_MCP.md"
                ),
                "account_required": False,
            },
            {
                "id": "ide-cli",
                "name": "Amosclaud IDE and Linux CLI",
                "kind": "cli",
                "url": f"{REPOSITORY}/blob/main/docs/AMOSCLAUD_IDE_COMPANION.md",
                "account_required": False,
            },
            {
                "id": "mcp",
                "name": "Amosclaud MCP server",
                "kind": "integration",
                "url": f"{REPOSITORY}/tree/main/amosclaud_mcp",
                "account_required": False,
            },
        ],
        "paid_amosclaud_features": {
            "account_required": True,
            "examples": [
                "hosted Autonomous engineering runs",
                "managed cloud workers and verification",
                "hosted model and OpenAI-compatible API usage",
                "managed repositories, operation buckets, and artifacts",
                "paid agent credits and commercial support",
            ],
            "plans_url": f"{origin}/plans",
            "login_url": f"{origin}/login",
        },
    }


@router.get("/developer-tools", include_in_schema=False)
def developer_tools_page() -> FileResponse:
    """Serve the public developer hub without requiring a session."""

    return FileResponse(WEB_ROOT / "developer-tools.html")


@router.get("/open-source", include_in_schema=False)
def open_source_alias() -> RedirectResponse:
    return RedirectResponse("/developer-tools", status_code=307)


__all__ = ["router", "open_source_tools"]

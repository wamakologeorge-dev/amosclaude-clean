"""MCP connector for the Amosclaud Autonomous Runtime."""

from __future__ import annotations

import os
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

BASE_URL = os.environ.get("AMOSCLAUD_BASE_URL", "https://amosclaud.com").rstrip("/")
API_KEY = os.environ.get("AMOSCLAUD_API_KEY", "")
TIMEOUT_SECONDS = float(os.environ.get("AMOSCLAUD_CONNECTOR_TIMEOUT", "120"))

mcp = FastMCP("amosclaud-autonomous-codex-connector")


def _headers() -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"
        headers["X-API-Key"] = API_KEY
    return headers


async def _request(method: str, path: str, **kwargs: Any) -> Any:
    url = f"{BASE_URL}{path}"
    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
        response = await client.request(method, url, headers=_headers(), **kwargs)
        response.raise_for_status()
        if not response.content:
            return {"ok": True, "status_code": response.status_code}
        return response.json()


@mcp.tool()
async def amosclaud_health() -> Any:
    """Check whether the Amosclaud application and autonomous runtime are reachable."""
    return await _request("GET", "/health")


@mcp.tool()
async def amosclaud_run(
    objective: str,
    mode: str = "autonomous-check",
    branch: str = "main",
) -> Any:
    """Run Amosclaud Autonomous without enabling the optional engineering agent."""
    allowed_modes = {"autonomous-check", "build", "monitor"}
    if mode not in allowed_modes:
        raise ValueError(f"mode must be one of: {', '.join(sorted(allowed_modes))}")

    payload = {
        "mode": mode,
        "objective": objective,
        "branch": branch,
        "metadata": {"use_agent": False, "connector": "codex"},
    }
    return await _request("POST", "/api/v1/agent/run", json=payload)


@mcp.tool()
async def amosclaud_pipeline(pipeline_id: str) -> Any:
    """Read the current state and logs for an Amosclaud pipeline."""
    if not pipeline_id.strip():
        raise ValueError("pipeline_id is required")
    return await _request("GET", f"/api/v1/pipelines/{pipeline_id}")


if __name__ == "__main__":
    mcp.run(transport="stdio")

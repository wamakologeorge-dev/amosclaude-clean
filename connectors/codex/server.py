"""MCP connector for the Amosclaud Autonomous Runtime."""

from __future__ import annotations

import os
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

BASE_URL = os.environ.get("AMOSCLAUD_BASE_URL", "https://amosclaud.com").rstrip("/")
API_KEY = os.environ.get("AMOSCLAUD_API_KEY", "")
TIMEOUT_SECONDS = float(os.environ.get("AMOSCLAUD_CONNECTOR_TIMEOUT", "180"))

mcp = FastMCP("amosclaud-autonomous-codex-connector")


def _headers() -> dict[str, str]:
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"
        headers["X-API-Key"] = API_KEY
    return headers


async def _request(method: str, path: str, **kwargs: Any) -> Any:
    url = f"{BASE_URL}{path}"
    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
        response = await client.request(method, url, headers=_headers(), **kwargs)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = response.text.strip() or exc.response.reason_phrase
            raise RuntimeError(f"Amosclaud request failed ({response.status_code}): {detail}") from exc
        if not response.content:
            return {"ok": True, "status_code": response.status_code}
        return response.json()


@mcp.tool()
async def amosclaud_health() -> Any:
    """Check whether the Amosclaud application and Autonomous runtime are reachable."""
    return await _request("GET", "/health")


@mcp.tool()
async def amosclaud_run(
    objective: str,
    mode: str = "autonomous-check",
    branch: str = "main",
    conversation_id: str | None = None,
    use_model: bool = False,
    apply_changes: bool = False,
) -> Any:
    """Run a user-mapped Autonomous task and return its final verified result.

    Modes: autonomous-check, build, fix, deploy, monitor. Set use_model=True
    to request model-assisted planning. File writes remain authorized only when
    apply_changes=True or when mode is fix.
    """
    allowed_modes = {"autonomous-check", "build", "fix", "deploy", "monitor"}
    if mode not in allowed_modes:
        raise ValueError(f"mode must be one of: {', '.join(sorted(allowed_modes))}")
    if not API_KEY:
        raise RuntimeError("AMOSCLAUD_API_KEY is required for the Codex connector")

    payload = {
        "mode": mode,
        "objective": objective,
        "branch": branch,
        "conversation_id": conversation_id,
        "use_model": use_model,
        "apply_changes": apply_changes,
        "metadata": {"connector": "codex"},
    }
    return await _request("POST", "/api/v1/agent/connector/run", json=payload)


@mcp.tool()
async def amosclaud_pipeline(pipeline_id: str) -> Any:
    """Read a legacy queued pipeline state and logs."""
    if not pipeline_id.strip():
        raise ValueError("pipeline_id is required")
    return await _request("GET", f"/api/v1/pipelines/{pipeline_id}")


if __name__ == "__main__":
    mcp.run(transport="stdio")

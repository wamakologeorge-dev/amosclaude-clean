"""First-party Model Context Protocol server for Amosclaud."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from amosclaud_mcp.client import AmosclaudClient, AmosclaudMCPError


mcp = FastMCP(
    "Amosclaud",
    instructions=(
        "Use Amosclaud to inspect real repositories, start governed Autonomous "
        "engineering work, and return pipeline evidence. Never claim a change was "
        "completed until the returned pipeline status and logs prove it."
    ),
)


def _call(method: str, /, **kwargs: Any) -> Any:
    try:
        with AmosclaudClient() as client:
            return getattr(client, method)(**kwargs)
    except AmosclaudMCPError as exc:
        raise RuntimeError(str(exc)) from exc


@mcp.tool()
def amosclaud_status() -> dict[str, Any]:
    """Check Amosclaud web health and Autonomous readiness."""

    return _call("status")


@mcp.tool()
def amosclaud_agent_profile() -> dict[str, Any]:
    """Return the mission and capabilities of the Amosclaud Autonomous Agent."""

    return _call("agent_profile")


@mcp.tool()
def run_autonomous(
    objective: str,
    repository_id: int | None = None,
    branch: str = "main",
    mode: str = "fix",
    apply_changes: bool = True,
) -> dict[str, Any]:
    """Start real Amosclaud engineering work in a repository.

    Use mode ``autonomous-check`` for inspection, ``build`` for a proposed build,
    ``fix`` for authorized repository changes, ``deploy`` for deployment work, or
    ``monitor`` for runtime monitoring. The result includes a pipeline ID that can
    be checked with ``get_pipeline_result``.
    """

    return _call(
        "run_autonomous",
        objective=objective,
        mode=mode,
        branch=branch,
        repository_id=repository_id,
        apply_changes=apply_changes,
    )


@mcp.tool()
def inspect_repository(
    repository_id: int,
    objective: str = "Inspect this repository and report the first verified blocker.",
    branch: str = "main",
) -> dict[str, Any]:
    """Inspect a real Amosclaud repository without applying changes."""

    return _call(
        "inspect_repository",
        repository_id=repository_id,
        objective=objective,
        branch=branch,
    )


@mcp.tool()
def get_pipeline_result(pipeline_id: str) -> dict[str, Any]:
    """Read the current status, jobs, logs, and evidence for one Autonomous run."""

    return _call("get_pipeline", pipeline_id=pipeline_id)


@mcp.tool()
def wait_for_pipeline_result(
    pipeline_id: str,
    timeout_seconds: int = 120,
    poll_interval_seconds: float = 2.0,
) -> dict[str, Any]:
    """Wait for an Autonomous pipeline to succeed, fail, or be cancelled."""

    return _call(
        "wait_for_pipeline",
        pipeline_id=pipeline_id,
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
    )


@mcp.tool()
def list_recent_pipelines() -> list[dict[str, Any]]:
    """List recent Amosclaud Autonomous and CI/CD pipeline runs."""

    return _call("list_recent_pipelines")


@mcp.resource("amosclaud://status")
def status_resource() -> dict[str, Any]:
    """Live Amosclaud service and Autonomous readiness."""

    return _call("status")


@mcp.prompt(title="Amosclaud Autonomous Engineering Task")
def autonomous_engineering_task(
    objective: str,
    repository_id: int,
    branch: str = "main",
) -> str:
    """Create a proof-first instruction for an Amosclaud engineering run."""

    return (
        "Use the Amosclaud MCP tools to complete this engineering objective:\n"
        f"{objective}\n\n"
        f"Repository ID: {repository_id}\n"
        f"Branch: {branch}\n\n"
        "First inspect the repository. Then run the smallest authorized change. "
        "Wait for the pipeline result and report the exact status, files, tests, "
        "commit or branch evidence, and any blocker. Do not claim success without "
        "verified pipeline evidence."
    )


def main() -> None:
    """Run the MCP server over standard input/output."""

    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()

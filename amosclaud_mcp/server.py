"""First-party Model Context Protocol server for Amosclaud."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from amosclaud_mcp.client import AmosclaudClient, AmosclaudMCPError

mcp = FastMCP(
    "Amosclaud",
    instructions=(
        "Use Amosclaud as the first-party developer control plane. Prefer native "
        "Amosclaud repository tools for repository reads and writes, and use the "
        "Autonomous tools for governed engineering execution and verification. "
        "Never claim a change was completed until returned commit or pipeline "
        "evidence proves it. External providers are implementation details behind "
        "Amosclaud and their credentials must never be requested from the user."
    ),
    stateless_http=True,
    json_response=True,
    streamable_http_path="/",
)


def _call(method: str, /, **kwargs: Any) -> Any:
    try:
        with AmosclaudClient() as client:
            return getattr(client, method)(**kwargs)
    except AmosclaudMCPError as exc:
        raise RuntimeError(str(exc)) from exc


# ---------------------------------------------------------------------------
# Connection and native repository provider
# ---------------------------------------------------------------------------


@mcp.tool()
def amosclaud_status() -> dict[str, Any]:
    """Read-only. Check Amosclaud web health and Autonomous readiness."""

    return _call("status")


@mcp.tool()
def amosclaud_connection() -> dict[str, Any]:
    """Read-only. Prove which Amosclaud account and scopes this connection uses."""

    return _call("mcp_identity")


@mcp.tool()
def list_repositories() -> list[dict[str, Any]]:
    """Read-only. List native Amosclaud repositories visible to this account."""

    return _call("list_repositories")


@mcp.tool()
def get_repository(repository_id: int) -> dict[str, Any]:
    """Read-only. Get one native Amosclaud repository record by numeric ID."""

    return _call("get_repository", repository_id=repository_id)


@mcp.tool()
def list_repository_tree(
    repository_id: int,
    branch: str = "main",
) -> list[dict[str, Any]]:
    """Read-only. List files and directories from an Amosclaud repository branch."""

    return _call("list_repository_tree", repository_id=repository_id, branch=branch)


@mcp.tool()
def read_repository_file(
    repository_id: int,
    path: str,
    branch: str = "main",
) -> dict[str, Any]:
    """Read-only. Read one UTF-8 file from an Amosclaud repository branch."""

    return _call(
        "read_repository_file",
        repository_id=repository_id,
        path=path,
        branch=branch,
    )


@mcp.tool()
def list_repository_branches(repository_id: int) -> list[str]:
    """Read-only. List branches stored by the native Amosclaud repository provider."""

    return _call("list_repository_branches", repository_id=repository_id)


@mcp.tool()
def list_repository_commits(
    repository_id: int,
    branch: str = "main",
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Read-only. List real commit history from an Amosclaud repository branch."""

    return _call(
        "list_repository_commits",
        repository_id=repository_id,
        branch=branch,
        limit=limit,
    )


@mcp.tool()
def create_repository(
    name: str,
    description: str = "",
    visibility: str = "private",
    initialize_readme: bool = True,
) -> dict[str, Any]:
    """WRITE ACTION. Create a native Amosclaud repository for this account."""

    return _call(
        "create_repository",
        name=name,
        description=description,
        visibility=visibility,
        initialize_readme=initialize_readme,
    )


@mcp.tool()
def create_repository_branch(
    repository_id: int,
    name: str,
    source_branch: str = "main",
) -> dict[str, Any]:
    """WRITE ACTION. Create a branch in a native Amosclaud repository."""

    return _call(
        "create_repository_branch",
        repository_id=repository_id,
        name=name,
        source_branch=source_branch,
    )


@mcp.tool()
def write_repository_file(
    repository_id: int,
    path: str,
    content: str,
    branch: str = "main",
    commit_message: str = "Update file through Amosclaud MCP",
) -> dict[str, Any]:
    """WRITE ACTION. Create or replace a file and commit it through Amosclaud."""

    return _call(
        "write_repository_file",
        repository_id=repository_id,
        path=path,
        content=content,
        branch=branch,
        commit_message=commit_message,
    )


@mcp.tool()
def delete_repository_file(
    repository_id: int,
    path: str,
    branch: str = "main",
    commit_message: str = "Delete file through Amosclaud MCP",
) -> dict[str, Any]:
    """WRITE ACTION. Delete a file or folder and commit through Amosclaud."""

    return _call(
        "delete_repository_file",
        repository_id=repository_id,
        path=path,
        branch=branch,
        commit_message=commit_message,
    )


# ---------------------------------------------------------------------------
# Agent and verified execution
# ---------------------------------------------------------------------------


@mcp.tool()
def amosclaud_agent_profile() -> dict[str, Any]:
    """Read-only. Return the mission and capabilities of the Amosclaud Autonomous Agent."""

    return _call("agent_profile")


@mcp.tool()
def run_autonomous(
    objective: str,
    repository_id: int | None = None,
    branch: str = "main",
    mode: str = "fix",
    apply_changes: bool = True,
) -> dict[str, Any]:
    """WRITE/EXECUTION ACTION. Start real Amosclaud engineering work.

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
    """Read/execute. Ask Amosclaud Autonomous to inspect without applying changes."""

    return _call(
        "inspect_repository",
        repository_id=repository_id,
        objective=objective,
        branch=branch,
    )


@mcp.tool()
def get_pipeline_result(pipeline_id: str) -> dict[str, Any]:
    """Read-only. Read status, jobs, logs, and evidence for an Autonomous run."""

    return _call("get_pipeline", pipeline_id=pipeline_id)


@mcp.tool()
def wait_for_pipeline_result(
    pipeline_id: str,
    timeout_seconds: int = 120,
    poll_interval_seconds: float = 2.0,
) -> dict[str, Any]:
    """Read-only. Wait for an Autonomous pipeline to reach a terminal state."""

    return _call(
        "wait_for_pipeline",
        pipeline_id=pipeline_id,
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
    )


@mcp.tool()
def list_recent_pipelines() -> list[dict[str, Any]]:
    """Read-only. List recent Amosclaud Autonomous and CI/CD pipeline runs."""

    return _call("list_recent_pipelines")


@mcp.resource("amosclaud://status")
def status_resource() -> dict[str, Any]:
    """Live Amosclaud service and Autonomous readiness."""

    return _call("status")


@mcp.resource("amosclaud://connection")
def connection_resource() -> dict[str, Any]:
    """Authenticated Amosclaud identity and connection metadata."""

    return _call("mcp_identity")


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
        "Read the repository through Amosclaud first. Then perform only the "
        "authorized change. Wait for the pipeline result and report the exact "
        "status, files, tests, commit or branch evidence, and any blocker. Do not "
        "request direct GitHub or infrastructure credentials and do not claim "
        "success without verified Amosclaud evidence."
    )


def main() -> None:
    """Run the MCP server over standard input/output."""

    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()

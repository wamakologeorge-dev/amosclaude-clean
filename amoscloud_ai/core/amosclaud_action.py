"""Allowlisted tools exposed by the Amosclaud-native Action."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from amoscloud_ai.core.amosclaud_authority import scope_allowed


@dataclass(frozen=True)
class ActionTool:
    """A discoverable tool contract; execution remains in its existing product API."""

    name: str
    title: str
    description: str
    required_scope: str
    access: str
    endpoint: str
    preserves_existing_integration: bool = True

    def public_dict(self) -> dict[str, Any]:
        return asdict(self)


ACTION_TOOLS: tuple[ActionTool, ...] = (
    ActionTool(
        "agent.answer",
        "Answer a user",
        "Return an Amosclaud answer through the authenticated agent surface.",
        "answer",
        "read",
        "POST /api/v1/agent/run",
    ),
    ActionTool(
        "agent.inspect",
        "Inspect evidence",
        "Inspect repository or workspace evidence before an engineering action.",
        "inspect",
        "read",
        "POST /api/v1/agent/run",
    ),
    ActionTool(
        "agent.plan",
        "Plan work",
        "Create a repository-aware plan without applying a change.",
        "plan",
        "read",
        "POST /api/v1/copilot/plan",
    ),
    ActionTool(
        "agent.build",
        "Build a change",
        "Start a governed Amosclaud build operation.",
        "build",
        "write",
        "POST /api/v1/agent/run",
    ),
    ActionTool(
        "agent.fix",
        "Fix a failure",
        "Start a governed Amosclaud repair operation.",
        "fix",
        "write",
        "POST /api/v1/agent/run",
    ),
    ActionTool(
        "agent.test",
        "Verify a change",
        "Request tests and evidence for a governed engineering operation.",
        "test",
        "write",
        "POST /api/v1/agent/run",
    ),
    ActionTool(
        "agent.deploy",
        "Deploy a change",
        "Request a governed deployment operation after verification.",
        "deploy",
        "write",
        "POST /api/v1/agent/run",
    ),
    ActionTool(
        "agent.monitor",
        "Monitor a change",
        "Read ongoing operation and deployment health.",
        "monitor",
        "read",
        "POST /api/v1/agent/run",
    ),
    ActionTool(
        "workspace.list",
        "List workspaces",
        "List workspaces available to the authenticated Amosclaud account.",
        "workspace:read",
        "read",
        "GET /api/v1/workspaces",
    ),
    ActionTool(
        "workspace.inspect",
        "Inspect a workspace",
        "Read the state and safe runtime URLs for one owned workspace.",
        "workspace:read",
        "read",
        "GET /api/v1/workspaces/{workspace_id}",
    ),
    ActionTool(
        "workspace.start",
        "Start a workspace",
        "Provision or start an owned developer workspace.",
        "workspace:write",
        "write",
        "POST /api/v1/workspaces/{workspace_id}/start",
    ),
    ActionTool(
        "workspace.stop",
        "Stop a workspace",
        "Stop an owned developer workspace.",
        "workspace:write",
        "write",
        "POST /api/v1/workspaces/{workspace_id}/stop",
    ),
    ActionTool(
        "workspace.restart",
        "Restart a workspace",
        "Restart an owned developer workspace.",
        "workspace:write",
        "write",
        "POST /api/v1/workspaces/{workspace_id}/restart",
    ),
    ActionTool(
        "repository.list",
        "List repositories",
        "List repositories visible to the authenticated Amosclaud account.",
        "repository:read",
        "read",
        "GET /api/v1/repositories",
    ),
    ActionTool(
        "repository.inspect",
        "Inspect a repository",
        "Read safe metadata and access role for one repository.",
        "repository:read",
        "read",
        "GET /api/v1/repositories/{repository_id}",
    ),
    ActionTool(
        "repository.write",
        "Change a repository",
        "Request a governed repository change through existing verification and branch controls.",
        "repository:write",
        "write",
        "POST /api/v1/repositories/{repository_id}/...",
    ),
    ActionTool(
        "task.create",
        "Create an operation",
        "Create a tracked Amosclaud operation in the owner's operation bucket.",
        "tasks:write",
        "write",
        "POST /api/v1/operations/...",
    ),
    ActionTool(
        "task.inspect",
        "Inspect an operation",
        "Read task status, logs, artifacts, and verification results.",
        "tasks:read",
        "read",
        "GET /api/v1/operations/...",
    ),
    ActionTool(
        "ci.list",
        "Read CI status",
        "Read CI and pipeline state without changing the existing CI provider.",
        "ci:read",
        "read",
        "GET /api/v1/pipelines/...",
    ),
    ActionTool(
        "ci.run",
        "Run CI",
        "Request a governed CI or verification run through the existing pipeline surface.",
        "ci:run",
        "write",
        "POST /api/v1/pipelines/...",
    ),
    ActionTool(
        "github.events.read",
        "Read GitHub events",
        "Read GitHub App events already recorded by Amosclaud.",
        "github:read",
        "read",
        "GET /api/v1/agent/github/events",
    ),
    ActionTool(
        "github.pull_request.read",
        "Read pull requests",
        "Read pull-request metadata through the existing GitHub integration.",
        "pull-requests:read",
        "read",
        "GET /api/v1/github/pull-requests/...",
    ),
    ActionTool(
        "github.pull_request.create",
        "Create a pull request",
        "Create a pull request through the existing governed GitHub integration.",
        "pull-requests:create",
        "write",
        "POST /api/v1/github/pull-requests/...",
    ),
    ActionTool(
        "github.pull_request.update",
        "Update a pull request",
        "Update an existing pull request without changing GitHub workflow definitions.",
        "pull-requests:update",
        "write",
        "PATCH /api/v1/github/pull-requests/...",
    ),
    ActionTool(
        "github.job.read",
        "Read GitHub jobs",
        "Read GitHub job status and logs through the existing integration.",
        "jobs:read",
        "read",
        "GET /api/v1/github/jobs/...",
    ),
    ActionTool(
        "github.job.update",
        "Update a GitHub job",
        "Request a governed job action through the existing GitHub integration.",
        "jobs:update",
        "write",
        "POST /api/v1/github/jobs/...",
    ),
    ActionTool(
        "deployment.read",
        "Read deployments",
        "Read deployment state and verification evidence.",
        "deployments:read",
        "read",
        "GET /api/v1/deployments/...",
    ),
    ActionTool(
        "deployment.run",
        "Run a deployment",
        "Request a governed deployment through existing deployment controls.",
        "deployments:run",
        "write",
        "POST /api/v1/deployments/...",
    ),
    ActionTool(
        "model.invoke",
        "Invoke the Amosclaud model",
        "Send a model request through the existing Amosclaud model gateway.",
        "model:invoke",
        "write",
        "POST /v1/responses or /v1/chat/completions",
    ),
    ActionTool(
        "terminal.open",
        "Open a terminal",
        "Request a short-lived, workspace-bound VS Code terminal ticket.",
        "workspace:write",
        "write",
        "GET /api/v1/vscode-terminal/repositories/...",
    ),
    ActionTool(
        "action.verify",
        "Verify Action authority",
        "Verify an Amosclaud Action credential and its current scopes.",
        "action:run",
        "read",
        "GET /api/v1/amosclaud/authority/verify",
    ),
)


def get_tool(name: str) -> ActionTool | None:
    wanted = str(name or "").strip()
    return next((tool for tool in ACTION_TOOLS if tool.name == wanted), None)


def catalog(*, required_scope: str | None = None) -> list[dict[str, Any]]:
    tools = ACTION_TOOLS
    if required_scope:
        tools = tuple(tool for tool in tools if tool.required_scope == required_scope)
    return [tool.public_dict() for tool in tools]


def authorize_tool(principal: dict[str, Any], name: str) -> dict[str, Any] | None:
    tool = get_tool(name)
    if tool is None:
        return None
    result = tool.public_dict()
    result["authorized"] = scope_allowed(principal, tool.required_scope)
    result["principal_type"] = principal.get("principal_type")
    result["workspace_id"] = principal.get("workspace_id")
    return result


__all__ = ["ACTION_TOOLS", "ActionTool", "authorize_tool", "catalog", "get_tool"]

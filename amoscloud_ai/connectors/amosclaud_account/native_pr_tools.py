"""First-class native repository, pull-request, and Action tools for Amosclaud MCP.

These tools intentionally call Amosclaud's own API surface. They do not call
GitHub, Railway, or another provider directly. Provider mirroring remains an
implementation detail behind the Amosclaud control plane.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Literal

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations

RequestAsUser = Callable[..., Awaitable[dict[str, Any]]]
RequireScope = Callable[[Context, str], tuple[int, dict[str, Any]]]


def _body_or_raise(result: dict[str, Any], *, operation: str) -> Any:
    """Return a successful Amosclaud API body or raise with durable evidence."""

    if result.get("ok"):
        return result.get("body")
    status = result.get("status_code", "unknown")
    body = result.get("body")
    raise RuntimeError(f"{operation} failed in Amosclaud ({status}): {body}")


def register_native_pr_tools(
    *,
    mcp: FastMCP,
    require_scope: RequireScope,
    request_as_user: RequestAsUser,
    read_annotations: ToolAnnotations,
    write_annotations: ToolAnnotations,
) -> None:
    """Register Amosclaud-native repository/PR/CI tools on an account MCP server."""

    @mcp.tool(annotations=read_annotations)
    async def amosclaud_list_repositories(ctx: Context) -> dict[str, Any]:
        """List repositories visible to the connected Amosclaud account."""

        user_id, _ = require_scope(ctx, "repositories:read")
        result = await request_as_user(
            user_id=user_id,
            method="GET",
            path="/api/v1/repositories",
        )
        repositories = _body_or_raise(result, operation="List repositories")
        return {
            "authority": "amosclaud",
            "repositories": repositories,
            "count": len(repositories) if isinstance(repositories, list) else None,
        }

    @mcp.tool(annotations=write_annotations)
    async def amosclaud_create_pull_request(
        repository_id: int,
        title: str,
        head_branch: str,
        ctx: Context,
        base_branch: str = "main",
        body: str = "",
    ) -> dict[str, Any]:
        """Create a native Amosclaud pull request from an existing work branch."""

        if repository_id <= 0:
            raise RuntimeError("repository_id must be a positive integer")
        cleaned_title = title.strip()
        if not cleaned_title:
            raise RuntimeError("title cannot be empty")
        if not head_branch.strip() or not base_branch.strip():
            raise RuntimeError("head_branch and base_branch cannot be empty")
        if head_branch.strip() == base_branch.strip():
            raise RuntimeError("head_branch and base_branch must differ")

        user_id, _ = require_scope(ctx, "repositories:write")
        result = await request_as_user(
            user_id=user_id,
            method="POST",
            path=f"/api/v1/repositories/{repository_id}/pull-requests",
            body={
                "title": cleaned_title,
                "body": body,
                "head_branch": head_branch.strip(),
                "base_branch": base_branch.strip(),
            },
        )
        pull_request = _body_or_raise(result, operation="Create pull request")
        return {
            "authority": "amosclaud",
            "repository_id": repository_id,
            "pull_request": pull_request,
        }

    @mcp.tool(annotations=read_annotations)
    async def amosclaud_list_pull_requests(
        repository_id: int,
        ctx: Context,
        include_deleted: bool = False,
    ) -> dict[str, Any]:
        """List native Amosclaud pull requests including control metadata.

        Set include_deleted=True to surface soft-deleted PRs that can be restored.
        """

        if repository_id <= 0:
            raise RuntimeError("repository_id must be a positive integer")
        user_id, _ = require_scope(ctx, "repositories:read")
        result = await request_as_user(
            user_id=user_id,
            method="GET",
            path=f"/api/v1/amosclaud/production/repositories/{repository_id}/pull-requests",
            query={"include_deleted": include_deleted} if include_deleted else None,
        )
        pull_requests = _body_or_raise(result, operation="List pull requests")
        return {
            "authority": "amosclaud",
            "repository_id": repository_id,
            "include_deleted": include_deleted,
            "pull_requests": pull_requests,
            "count": len(pull_requests) if isinstance(pull_requests, list) else None,
        }

    @mcp.tool(annotations=read_annotations)
    async def amosclaud_get_pull_request(
        repository_id: int,
        pull_request_id: int,
        ctx: Context,
        include_deleted: bool = False,
    ) -> dict[str, Any]:
        """Get one native Amosclaud pull request and its latest Action evidence."""

        if repository_id <= 0 or pull_request_id <= 0:
            raise RuntimeError("repository_id and pull_request_id must be positive integers")
        user_id, _ = require_scope(ctx, "repositories:read")
        prs_result = await request_as_user(
            user_id=user_id,
            method="GET",
            path=f"/api/v1/amosclaud/production/repositories/{repository_id}/pull-requests",
            query={"include_deleted": include_deleted} if include_deleted else None,
        )
        pull_requests = _body_or_raise(prs_result, operation="Get pull request")
        if not isinstance(pull_requests, list):
            raise RuntimeError("Amosclaud returned an invalid pull-request collection")
        pull_request = next(
            (item for item in pull_requests if int(item.get("id", 0)) == pull_request_id),
            None,
        )
        if pull_request is None:
            raise RuntimeError("Pull request not found in the connected Amosclaud account")

        ci_result = await request_as_user(
            user_id=user_id,
            method="GET",
            path=(
                f"/api/v1/amosclaud/production/repositories/{repository_id}"
                f"/pull-requests/{pull_request_id}/ci"
            ),
        )
        checks = _body_or_raise(ci_result, operation="Read pull request checks")
        return {
            "authority": "amosclaud",
            "repository_id": repository_id,
            "pull_request": pull_request,
            "checks": checks,
        }

    @mcp.tool(annotations=write_annotations)
    async def amosclaud_run_pull_request_checks(
        repository_id: int,
        pull_request_id: int,
        ctx: Context,
        commit_sha: str | None = None,
        reason: str = "Amosclaud MCP pull-request verification",
    ) -> dict[str, Any]:
        """Run authoritative Amosclaud Actions for an open native pull request."""

        if repository_id <= 0 or pull_request_id <= 0:
            raise RuntimeError("repository_id and pull_request_id must be positive integers")
        user_id, _ = require_scope(ctx, "repositories:write")
        request_body: dict[str, Any] = {
            "branch": "main",
            "reason": reason.strip() or "Amosclaud MCP pull-request verification",
        }
        if commit_sha:
            request_body["commit_sha"] = commit_sha.strip()
        result = await request_as_user(
            user_id=user_id,
            method="POST",
            path=(
                f"/api/v1/amosclaud/production/repositories/{repository_id}"
                f"/pull-requests/{pull_request_id}/ci"
            ),
            body=request_body,
        )
        evidence = _body_or_raise(result, operation="Run Amosclaud Action")
        return {
            "authority": "amosclaud",
            "authoritative": True,
            "repository_id": repository_id,
            "pull_request_id": pull_request_id,
            "evidence": evidence,
        }

    @mcp.tool(annotations=read_annotations)
    async def amosclaud_get_pull_request_checks(
        repository_id: int,
        pull_request_id: int,
        ctx: Context,
    ) -> dict[str, Any]:
        """Read authoritative Amosclaud Action history for one pull request."""

        if repository_id <= 0 or pull_request_id <= 0:
            raise RuntimeError("repository_id and pull_request_id must be positive integers")
        user_id, _ = require_scope(ctx, "repositories:read")
        result = await request_as_user(
            user_id=user_id,
            method="GET",
            path=(
                f"/api/v1/amosclaud/production/repositories/{repository_id}"
                f"/pull-requests/{pull_request_id}/ci"
            ),
        )
        evidence = _body_or_raise(result, operation="Read Amosclaud Action history")
        return {
            "authority": "amosclaud",
            "authoritative": True,
            "repository_id": repository_id,
            "pull_request_id": pull_request_id,
            "evidence": evidence,
        }

    @mcp.tool(annotations=write_annotations)
    async def amosclaud_control_pull_request(
        repository_id: int,
        pull_request_id: int,
        action: Literal["close", "reopen", "delete", "restore"],
        ctx: Context,
    ) -> dict[str, Any]:
        """Close, reopen, delete, or restore a native Amosclaud pull request."""

        if repository_id <= 0 or pull_request_id <= 0:
            raise RuntimeError("repository_id and pull_request_id must be positive integers")
        user_id, _ = require_scope(ctx, "repositories:write")
        result = await request_as_user(
            user_id=user_id,
            method="POST",
            path=(
                f"/api/v1/amosclaud/production/repositories/{repository_id}"
                f"/pull-requests/{pull_request_id}/action"
            ),
            body={"action": action},
        )
        pull_request = _body_or_raise(result, operation=f"{action.title()} pull request")
        return {
            "authority": "amosclaud",
            "repository_id": repository_id,
            "pull_request_id": pull_request_id,
            "action": action,
            "result": pull_request,
        }

    @mcp.tool(annotations=write_annotations)
    async def amosclaud_merge_pull_request(
        repository_id: int,
        pull_request_id: int,
        ctx: Context,
    ) -> dict[str, Any]:
        """Merge a native PR only through Amosclaud's verified merge gate.

        Amosclaud itself checks that the latest authoritative Action succeeded for
        the exact current PR head SHA. This tool cannot bypass that gate.
        """

        if repository_id <= 0 or pull_request_id <= 0:
            raise RuntimeError("repository_id and pull_request_id must be positive integers")
        user_id, _ = require_scope(ctx, "repositories:write")
        result = await request_as_user(
            user_id=user_id,
            method="POST",
            path=(
                f"/api/v1/amosclaud/production/repositories/{repository_id}"
                f"/pull-requests/{pull_request_id}/action"
            ),
            body={"action": "merge"},
        )
        merged = _body_or_raise(result, operation="Merge pull request")
        return {
            "authority": "amosclaud",
            "authoritative": True,
            "repository_id": repository_id,
            "pull_request_id": pull_request_id,
            "result": merged,
        }

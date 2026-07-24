"""Server-authorized execution for real Amosclaud OS engineering operations."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from amoscloud_ai.api.routes import auth as auth_routes
from amoscloud_ai.api.routes import repositories
from amosclaud_os.repository.issues import NativeIssueService
from amosclaud_os.workspace.context import ProjectContextSelection, ProjectContextService

_CREATE_REPOSITORY = re.compile(
    r"\b(?:create|initialize|start|make)\s+(?:a\s+|an\s+|new\s+)?repository"
    r"(?:\s+(?:named|called))?\s*[:\-]?\s*([A-Za-z0-9][A-Za-z0-9._-]{0,99})?",
    re.IGNORECASE,
)
_CREATE_ISSUE = re.compile(r"\b(?:create|open|add|file)\b.*\b(?:issue|ticket)\b", re.IGNORECASE)
_NO_WRITE = re.compile(r"\b(?:do not|don't|never)\s+(?:edit|change|write|modify|execute|create)\b", re.IGNORECASE)


@dataclass
class NativeExecutionResult:
    operation: str
    status: str
    summary: str
    evidence: list[str] = field(default_factory=list)
    resource: dict[str, Any] | None = None
    logs: list[str] = field(default_factory=list)

    @property
    def succeeded(self) -> bool:
        return self.status == "success"

    def check(self) -> dict[str, Any]:
        return {
            "name": self.operation,
            "status": "passed" if self.succeeded else "failed",
            "summary": self.summary,
            "details": self.evidence,
        }


def _context_service() -> ProjectContextService:
    return ProjectContextService(auth_routes.DB_PATH)


def _operation(objective: str, metadata: dict[str, Any]) -> str | None:
    explicit = str(metadata.get("operation") or "").strip().lower()
    if explicit in {"create_repository", "create_issue", "write_file", "list_issues"}:
        return explicit
    if _CREATE_REPOSITORY.search(objective):
        return "create_repository"
    if _CREATE_ISSUE.search(objective):
        return "create_issue"
    return None


def _repository_name(objective: str, metadata: dict[str, Any]) -> str:
    supplied = str(
        metadata.get("new_repository_name")
        or metadata.get("repository_name_to_create")
        or ""
    ).strip()
    if supplied:
        return supplied
    match = _CREATE_REPOSITORY.search(objective)
    return str(match.group(1) if match and match.group(1) else "").strip()


def _issue_title(objective: str, metadata: dict[str, Any]) -> str:
    supplied = str(metadata.get("issue_title") or "").strip()
    if supplied:
        return supplied
    cleaned = re.sub(r"^@?amosclaud\s*", "", objective, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(?:create|open|add|file|new)\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(?:an?|the)?\s*(?:issue|ticket)\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .:-")
    return cleaned[:200]


def _selected_repository(user, metadata: dict[str, Any]) -> tuple[int | None, dict[str, Any]]:
    context = _context_service().resolve(int(user["id"]))
    repository_id = metadata.get("repository_id") or context.repository_id
    return (int(repository_id) if repository_id else None, context.model_dump())


def _failure(operation: str, summary: str, *evidence: str) -> NativeExecutionResult:
    return NativeExecutionResult(
        operation=operation,
        status="failed",
        summary=summary,
        evidence=[item for item in evidence if item],
        logs=[summary, *[item for item in evidence if item]],
    )


def execute_native_operation(
    *,
    user,
    objective: str,
    mode: str,
    metadata: dict[str, Any] | None = None,
) -> NativeExecutionResult | None:
    """Execute deterministic native operations, then real model-backed repository work.

    Returning ``None`` is reserved for ordinary conversation. Engineering requests
    always return a truthful success or blocker and never a simulated completion.
    """

    prepared = dict(metadata or {})
    objective = " ".join((objective or "").strip().split())
    operation = _operation(objective, prepared)
    action_requested = bool(
        operation
        or prepared.get("use_agent")
        or prepared.get("apply_changes")
        or mode in {"build", "fix", "deploy"}
    )
    if not action_requested:
        return None
    if _NO_WRITE.search(objective):
        return _failure(
            operation or "engineering-command",
            "Execution was not started because the command explicitly forbids changes.",
            "No repository mutation occurred.",
        )

    try:
        if operation == "create_repository":
            name = _repository_name(objective, prepared)
            if not name:
                return _failure(
                    operation,
                    "A repository name is required before Amosclaud can create it.",
                    "Example: Create a repository named customer-portal",
                )
            created = repositories.create_repository(
                repositories.RepositoryCreate(
                    name=name,
                    description=str(prepared.get("repository_description") or objective)[:500],
                    visibility=str(prepared.get("visibility") or "private"),
                    initialize_readme=True,
                ),
                user,
            )
            context = _context_service().select(
                int(user["id"]),
                ProjectContextSelection(
                    repository_id=int(created.id),
                    branch=created.default_branch,
                ),
            )
            resource = created.model_dump()
            return NativeExecutionResult(
                operation=operation,
                status="success",
                summary=f"Created native repository {created.name} and selected it as the active project.",
                evidence=[
                    f"Repository ID: {created.id}",
                    f"Storage: {repositories._repo_path(int(created.id))}",
                    f"Default branch: {created.default_branch}",
                    f"Active context: {context.repository_name}@{context.branch}",
                ],
                resource=resource,
                logs=[
                    "Repository database record created.",
                    "Native Git repository initialized.",
                    "Starter files committed.",
                    "Project context persisted for the signed-in user.",
                ],
            )

        repository_id, context = _selected_repository(user, prepared)
        if not repository_id:
            return _failure(
                operation or "engineering-command",
                "No native Amosclaud repository is selected.",
                "Create a repository first, for example: Create a repository named my-project",
                "The platform did not run against its own application source as a substitute.",
            )

        if operation == "create_issue":
            title = _issue_title(objective, prepared)
            if not title:
                return _failure(
                    operation,
                    "An issue title is required.",
                    "No issue was created.",
                )
            issue = NativeIssueService().create(
                user=user,
                repository_id=repository_id,
                title=title,
                description=str(prepared.get("issue_description") or objective),
            )
            return NativeExecutionResult(
                operation=operation,
                status="success",
                summary=f"Created issue #{issue['number']}: {issue['title']}",
                evidence=[
                    f"Repository ID: {repository_id}",
                    f"Issue database ID: {issue['id']}",
                    f"State: {issue['state']}",
                    f"Created at: {issue['created_at']}",
                ],
                resource=issue,
                logs=[
                    "Repository permission verified on the server.",
                    "Issue persisted in the native Amosclaud database.",
                    "Repository activity timestamp updated.",
                ],
            )

        if operation == "list_issues":
            issues = NativeIssueService().list(
                user=user,
                repository_id=repository_id,
                state=str(prepared.get("issue_state") or "") or None,
            )
            return NativeExecutionResult(
                operation=operation,
                status="success",
                summary=f"Loaded {len(issues)} native issue(s).",
                evidence=[f"Repository ID: {repository_id}", f"Issue count: {len(issues)}"],
                resource={"items": issues},
                logs=["Repository access verified.", "Native issues read from persistent storage."],
            )

        if operation == "write_file":
            path = str(prepared.get("file_path") or prepared.get("path") or "").strip()
            content = prepared.get("file_content")
            if not path or not isinstance(content, str):
                return _failure(
                    operation,
                    "A file path and complete file content are required for deterministic writing.",
                    "No file was changed.",
                )
            result = repositories.write_file(
                repository_id,
                repositories.FileWriteRequest(
                    path=path,
                    content=content,
                    branch=str(prepared.get("branch") or context.get("branch") or "main"),
                    commit_message=str(prepared.get("commit_message") or f"Update {path}")[:200],
                ),
                user,
            )
            return NativeExecutionResult(
                operation=operation,
                status="success",
                summary=f"Wrote {path} and created commit {result['commit'][:12]}.",
                evidence=[
                    f"Repository ID: {repository_id}",
                    f"Branch: {result['branch']}",
                    f"Commit: {result['commit']}",
                ],
                resource=result,
                logs=["Write permission verified.", "File written inside the native repository.", "Git commit created."],
            )

        # A general build or repair requires a genuine model endpoint. It executes
        # against the selected native repository, never against the platform source.
        from src.agent.actions import run_autonomous
        from src.agent.model import load_model_config

        config = load_model_config()
        if not config.endpoint:
            return _failure(
                "model-backed-engineering",
                "Real code generation is unavailable because no Amosclaud model endpoint is connected.",
                f"Selected repository: {context.get('repository_name') or repository_id}",
                "Deterministic repository, issue, branch, commit, and supplied-file operations remain available.",
                "Configure AMOSCLAUD_MODEL_ENDPOINT or AMOSCLAUD_MODEL_URL to enable model-generated code changes.",
            )

        with repositories._db() as db:
            access = repositories._access(db, repository_id, int(user["id"]))
            repositories._require_write(access)
            role = str(access["role"] or "viewer")
        workspace = repositories._repo_path(repository_id)
        if not Path(workspace).is_dir():
            return _failure(
                "model-backed-engineering",
                "The selected repository storage is unavailable.",
                f"Expected storage: {workspace}",
            )
        execution_mode = "fix" if mode in {"build", "fix"} or prepared.get("apply_changes") else "plan"
        raw = run_autonomous(
            objective=objective,
            mode=execution_mode,
            authorized_writes=role in {"owner", "developer"},
            workspace=str(workspace),
            metadata={
                **prepared,
                "repository_id": repository_id,
                "repository_role": role,
                "authorization_source": "signed-in-session",
            },
        )
        raw_status = str(raw.get("status") or "failed").lower()
        changed = [str(item) for item in raw.get("changed_files") or []]
        checks = list(raw.get("checks") or [])
        succeeded = raw_status == "success" and (execution_mode != "fix" or bool(changed))
        summary = (
            f"Changed {len(changed)} file(s) in the native repository and completed verification."
            if succeeded
            else str(raw.get("blocker") or "The engineering runtime did not produce a verified repository change.")
        )
        evidence = [f"Repository ID: {repository_id}", f"Workspace: {workspace}"]
        evidence.extend(f"Changed: {path}" for path in changed)
        evidence.extend(
            str(item.get("summary") or item)
            for item in checks[:20]
            if isinstance(item, dict) or item
        )
        return NativeExecutionResult(
            operation="model-backed-engineering",
            status="success" if succeeded else "failed",
            summary=summary,
            evidence=evidence,
            resource=raw,
            logs=[
                f"Model endpoint: {config.endpoint}",
                f"Model: {config.model}",
                f"Execution workspace: {workspace}",
                f"Runtime status: {raw_status}",
            ],
        )
    except HTTPException as exc:
        return _failure(
            operation or "engineering-command",
            str(exc.detail),
            f"HTTP status: {exc.status_code}",
            "No success was reported.",
        )
    except Exception as exc:
        return _failure(
            operation or "engineering-command",
            f"Execution failed safely: {type(exc).__name__}",
            str(exc),
            "No success was reported without evidence.",
        )

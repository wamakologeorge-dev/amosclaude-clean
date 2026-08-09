"""Route failed security workflows into the existing Amosclaud repair loop.

This bridge runs only from trusted default-branch code. It authenticates the
Amosclaud GitHub App, verifies that the failed workflow still belongs to the
current open pull-request head, and dispatches the existing Repair Control Plane.
It does not execute pull-request code, generate patches, push, merge, or dismiss
security findings.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from .github_app_connection import (
    GitHubAppConnectionError,
    InstallationConnection,
    connect_installation,
)

SECURITY_WORKFLOWS = frozenset(
    {
        "CodeQL",
        "Amosclaud CodeQL Threat Gate",
        "Amosclaud Dependency Threat Gate",
        "Fortify AST Scan",
    }
)
BLOCKING_CONCLUSIONS = frozenset({"action_required", "failure", "startup_failure", "timed_out"})
REPAIR_WORKFLOW = "amosclaud-repair-control-plane.yml"
GitHubRequest = Callable[
    [str, str, Mapping[str, str], Mapping[str, object] | None],
    tuple[int, object],
]


@dataclass(frozen=True)
class BridgeResult:
    status: str
    workflow: str
    conclusion: str
    pull_request: int | None = None
    target_sha: str | None = None
    repair_dispatched: bool = False
    detail: str = ""

    @property
    def exit_code(self) -> int:
        return 1 if self.status == "BLOCKED" else 0

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": "amosclaud.security-repair-bridge.v1",
            "status": self.status,
            "workflow": self.workflow,
            "conclusion": self.conclusion,
            "pull_request": self.pull_request,
            "target_sha": self.target_sha,
            "repair_dispatched": self.repair_dispatched,
            "detail": self.detail,
            "sensitive_value_disclosed": False,
            "exit_code": self.exit_code,
        }


def _http_request(
    method: str,
    url: str,
    headers: Mapping[str, str],
    payload: Mapping[str, object] | None,
) -> tuple[int, object]:
    try:
        with httpx.Client(timeout=20.0, follow_redirects=False) as client:
            response = client.request(method, url, headers=dict(headers), json=payload)
        if not response.content:
            data: object = {}
        else:
            data = response.json()
        return response.status_code, data
    except (httpx.HTTPError, ValueError):
        return 0, {}


def _headers(token: str) -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _workflow_run(event: Mapping[str, object]) -> Mapping[str, object]:
    value = event.get("workflow_run")
    return value if isinstance(value, Mapping) else {}


def _pull_number_from_run(run: Mapping[str, object]) -> int | None:
    pull_requests = run.get("pull_requests")
    if not isinstance(pull_requests, list):
        return None
    for item in pull_requests:
        if not isinstance(item, Mapping):
            continue
        number = item.get("number")
        if isinstance(number, int) and number > 0:
            return number
    return None


def _resolve_pull_number(
    *,
    repository: str,
    head_sha: str,
    run: Mapping[str, object],
    connection: InstallationConnection,
    request: GitHubRequest,
) -> int | None:
    number = _pull_number_from_run(run)
    if number is not None:
        return number

    status, payload = request(
        "GET",
        f"https://api.github.com/repos/{repository}/commits/{quote(head_sha, safe='')}/pulls",
        _headers(connection.token),
        None,
    )
    if status != 200 or not isinstance(payload, list):
        return None
    for item in payload:
        if not isinstance(item, Mapping) or item.get("state") != "open":
            continue
        candidate = item.get("number")
        if isinstance(candidate, int) and candidate > 0:
            return candidate
    return None


def bridge_security_failure(
    *,
    repository: str,
    event: Mapping[str, object],
    connection: InstallationConnection,
    request: GitHubRequest = _http_request,
) -> BridgeResult:
    run = _workflow_run(event)
    workflow = str(run.get("name") or "").strip()
    conclusion = str(run.get("conclusion") or "").strip().lower()
    head_sha = str(run.get("head_sha") or "").strip()

    if workflow not in SECURITY_WORKFLOWS:
        return BridgeResult(
            "NOT_APPLICABLE",
            workflow,
            conclusion,
            detail="workflow is not an approved Amosclaud security source",
        )
    if conclusion not in BLOCKING_CONCLUSIONS:
        return BridgeResult(
            "NOT_APPLICABLE",
            workflow,
            conclusion,
            detail="security workflow did not end in a repairable blocking conclusion",
        )
    if not head_sha:
        return BridgeResult(
            "BLOCKED",
            workflow,
            conclusion,
            detail="failed security workflow did not expose an exact head SHA",
        )

    pull_number = _resolve_pull_number(
        repository=repository,
        head_sha=head_sha,
        run=run,
        connection=connection,
        request=request,
    )
    if pull_number is None:
        return BridgeResult(
            "NO_OPEN_PULL_REQUEST",
            workflow,
            conclusion,
            target_sha=head_sha,
            detail="no open pull request is associated with the failed security revision",
        )

    status, pull_payload = request(
        "GET",
        f"https://api.github.com/repos/{repository}/pulls/{pull_number}",
        _headers(connection.token),
        None,
    )
    if status != 200 or not isinstance(pull_payload, Mapping):
        return BridgeResult(
            "BLOCKED",
            workflow,
            conclusion,
            pull_request=pull_number,
            target_sha=head_sha,
            detail="pull-request verification failed",
        )

    current_sha = str(
        (pull_payload.get("head") or {}).get("sha")
        if isinstance(pull_payload.get("head"), Mapping)
        else ""
    ).strip()
    state = str(pull_payload.get("state") or "").strip().lower()
    if state != "open":
        return BridgeResult(
            "NO_OPEN_PULL_REQUEST",
            workflow,
            conclusion,
            pull_request=pull_number,
            target_sha=head_sha,
            detail="the associated pull request is no longer open",
        )
    if current_sha != head_sha:
        return BridgeResult(
            "STALE_SECURITY_RESULT",
            workflow,
            conclusion,
            pull_request=pull_number,
            target_sha=head_sha,
            detail="the pull-request head moved; no stale repair was dispatched",
        )

    repository_payload = event.get("repository")
    default_branch = (
        str(repository_payload.get("default_branch") or "").strip()
        if isinstance(repository_payload, Mapping)
        else ""
    )
    if not default_branch:
        status, repo_payload = request(
            "GET",
            f"https://api.github.com/repos/{repository}",
            _headers(connection.token),
            None,
        )
        if status == 200 and isinstance(repo_payload, Mapping):
            default_branch = str(repo_payload.get("default_branch") or "").strip()
    if not default_branch:
        return BridgeResult(
            "BLOCKED",
            workflow,
            conclusion,
            pull_request=pull_number,
            target_sha=head_sha,
            detail="default branch could not be resolved",
        )

    run_id = str(run.get("id") or "")
    run_url = str(run.get("html_url") or "")
    failure_summary = (
        f"Security threat source `{workflow}` ended with `{conclusion}` for exact "
        f"revision `{head_sha}`. Treat the finding as blocking; repair the root cause "
        "without suppressing, dismissing, or weakening the security control."
    )
    dispatch_payload = {
        "ref": default_branch,
        "inputs": {
            "scope": "pull_request",
            "pull_request_number": str(pull_number),
            "target_sha": head_sha,
            "source_run_id": run_id,
            "source_name": workflow,
            "provider": "github_actions",
            "status_url": run_url,
            "failure_summary": failure_summary,
        },
    }
    status, _ = request(
        "POST",
        (
            f"https://api.github.com/repos/{repository}/actions/workflows/"
            f"{REPAIR_WORKFLOW}/dispatches"
        ),
        _headers(connection.token),
        dispatch_payload,
    )
    if status != 204:
        return BridgeResult(
            "BLOCKED",
            workflow,
            conclusion,
            pull_request=pull_number,
            target_sha=head_sha,
            detail=f"Repair Control Plane dispatch failed with status {status or 'network-error'}",
        )

    return BridgeResult(
        "REPAIR_DISPATCHED",
        workflow,
        conclusion,
        pull_request=pull_number,
        target_sha=head_sha,
        repair_dispatched=True,
        detail="verified security failure was routed to the existing bounded repair loop",
    )


def run_from_environment() -> int:
    event_path = os.getenv("GITHUB_EVENT_PATH", "")
    repository = os.getenv("GITHUB_REPOSITORY", "")
    if not event_path or not repository:
        result = BridgeResult(
            "BLOCKED",
            "",
            "",
            detail="GITHUB_EVENT_PATH and GITHUB_REPOSITORY are required",
        )
        print(json.dumps(result.as_dict(), sort_keys=True))
        return result.exit_code

    try:
        event = json.loads(Path(event_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        result = BridgeResult(
            "BLOCKED",
            "",
            "",
            detail="workflow event could not be read safely",
        )
        print(json.dumps(result.as_dict(), sort_keys=True))
        return result.exit_code

    try:
        connection = connect_installation(repository=repository)
    except GitHubAppConnectionError as exc:
        result = BridgeResult(
            "BLOCKED",
            str(_workflow_run(event).get("name") or ""),
            str(_workflow_run(event).get("conclusion") or ""),
            detail=f"GitHub App connection failed: {exc.code}",
        )
        print(json.dumps(result.as_dict(), sort_keys=True))
        return result.exit_code

    result = bridge_security_failure(
        repository=repository,
        event=event,
        connection=connection,
    )
    print(json.dumps(result.as_dict(), sort_keys=True))
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(run_from_environment())

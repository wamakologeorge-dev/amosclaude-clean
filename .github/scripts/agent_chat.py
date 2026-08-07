#!/usr/bin/env python3
"""Explain GitHub Actions failures and route bounded Amosclaud repairs.

This script runs from the trusted default branch. It never executes pull-request
code. It reads GitHub metadata and redacted job logs, posts one durable PR
explanation, and optionally dispatches the existing Repair Control Plane.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

API_ROOT = "https://api.github.com"
COMMENT_MARKER = "<!-- amosclaud-agent-chat -->"
RUN_MARKER_PREFIX = "<!-- amosclaud-agent-chat-run:"
TRUSTED_ASSOCIATIONS = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})
REPAIRABLE_CONCLUSIONS = frozenset({"failure", "timed_out", "action_required"})
NON_REPAIRABLE_CONCLUSIONS = frozenset(
    {"cancelled", "neutral", "skipped", "stale", "startup_failure"}
)
SKIP_WORKFLOWS = frozenset(
    {
        "Amosclaud Agent Chat",
        "Amosclaud Agent Main",
        "Amosclaud Repair Results",
        "Amosclaud Repair Control Plane",
        "Amosclaud Scan Bug",
    }
)
MAX_LOG_BYTES = 1_500_000
MAX_EVIDENCE_LINES = 18
MAX_FAILURE_SUMMARY = 5_000

SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(api[_-]?key|token|secret|password|passwd|private[_-]?key)"
    r"(\s*[:=]\s*)([^\s,;]+)"
)
AUTHORIZATION_HEADER = re.compile(r"(?i)(authorization\s*:\s*)([^\r\n]+)")
BEARER_VALUE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}")
GITHUB_CREDENTIAL = re.compile(r"\b(?:gh[pousr]_|github_pat_)[A-Za-z0-9_]{8,}")
ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

EVIDENCE_PATTERNS = (
    re.compile(r"forbidden root artifacts", re.IGNORECASE),
    re.compile(r"would reformat", re.IGNORECASE),
    re.compile(r"FAILED(?:\s|$)"),
    re.compile(r"AssertionError"),
    re.compile(r"SyntaxError|IndentationError"),
    re.compile(r"ModuleNotFoundError|ImportError"),
    re.compile(r"Resource not accessible", re.IGNORECASE),
    re.compile(r"No space left on device", re.IGNORECASE),
    re.compile(r"Process completed with exit code", re.IGNORECASE),
    re.compile(r"##\[error\]", re.IGNORECASE),
)


class GitHubAPIError(RuntimeError):
    """Raised when GitHub rejects a repository-doctor operation."""


@dataclass(slots=True)
class Diagnosis:
    category: str
    title: str
    explanation: str
    proposed_fix: str
    evidence: list[str]
    failed_jobs: list[str]
    repairable: bool


@dataclass(slots=True)
class DoctorResult:
    workflow_name: str
    conclusion: str
    run_id: int
    run_attempt: int
    target_sha: str
    pull_request_number: int | None
    diagnosis: Diagnosis
    repair_requested: bool = False
    repair_dispatch_error: str = ""
    comment_url: str = ""


def redact(value: str) -> str:
    """Remove credentials while preserving useful failure context."""

    value = ANSI_ESCAPE.sub("", value)
    value = AUTHORIZATION_HEADER.sub(r"\1[REDACTED]", value)
    value = SECRET_ASSIGNMENT.sub(
        lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]", value
    )
    value = BEARER_VALUE.sub("Bearer [REDACTED]", value)
    return GITHUB_CREDENTIAL.sub("[REDACTED GITHUB CREDENTIAL]", value)


def _headers(token: str, *, json_body: bool = False) -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "amosclaud-agent-chat",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if json_body:
        headers["Content-Type"] = "application/json"
    return headers


def api_bytes(
    token: str,
    path: str,
    *,
    method: str = "GET",
    payload: Mapping[str, Any] | None = None,
) -> bytes:
    body = json.dumps(dict(payload)).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        f"{API_ROOT}{path}",
        data=body,
        method=method,
        headers=_headers(token, json_body=payload is not None),
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            return response.read(MAX_LOG_BYTES + 1)[:MAX_LOG_BYTES]
    except urllib.error.HTTPError as exc:
        detail = exc.read(4_096).decode("utf-8", errors="replace")
        raise GitHubAPIError(
            f"GitHub API {method} {path} returned {exc.code}: {redact(detail)}"
        ) from exc
    except urllib.error.URLError as exc:
        raise GitHubAPIError(f"GitHub API request failed: {exc.reason}") from exc


def api_json(
    token: str,
    path: str,
    *,
    method: str = "GET",
    payload: Mapping[str, Any] | None = None,
) -> Any:
    raw = api_bytes(token, path, method=method, payload=payload)
    return json.loads(raw.decode("utf-8", errors="replace")) if raw else {}


def decode_job_log(raw: bytes) -> str:
    if raw.startswith(b"PK"):
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            chunks = [
                archive.read(name).decode("utf-8", errors="replace")
                for name in sorted(archive.namelist())
                if not name.endswith("/")
            ]
        return redact("\n".join(chunks))
    return redact(raw.decode("utf-8", errors="replace"))


def repository_default_branch(token: str, repository: str) -> str:
    payload = api_json(token, f"/repos/{repository}")
    return str(payload.get("default_branch") or "main")


def pull_request_for_sha(token: str, repository: str, sha: str) -> int | None:
    if not sha:
        return None
    payload = api_json(
        token,
        f"/repos/{repository}/commits/{urllib.parse.quote(sha)}/pulls",
    )
    open_items = [item for item in payload if item.get("state") == "open"]
    return int(open_items[0]["number"]) if open_items else None


def pull_request_for_run(
    token: str,
    repository: str,
    run: Mapping[str, Any],
) -> int | None:
    pull_requests = run.get("pull_requests") or []
    if pull_requests and pull_requests[0].get("number"):
        return int(pull_requests[0]["number"])
    return pull_request_for_sha(token, repository, str(run.get("head_sha") or ""))


def failed_jobs_and_logs(
    token: str,
    repository: str,
    run_id: int,
) -> tuple[list[str], str]:
    payload = api_json(
        token,
        f"/repos/{repository}/actions/runs/{run_id}/jobs?filter=latest&per_page=100",
    )
    failed = [
        job
        for job in payload.get("jobs", [])
        if str(job.get("conclusion") or "")
        in {"failure", "timed_out", "action_required", "cancelled"}
    ]
    names: list[str] = []
    logs: list[str] = []
    for job in failed[:8]:
        name = str(job.get("name") or f"job-{job.get('id')}")
        names.append(name)
        try:
            raw = api_bytes(
                token,
                f"/repos/{repository}/actions/jobs/{int(job['id'])}/logs",
            )
            logs.append(f"\n=== {name} ===\n{decode_job_log(raw)}")
        except (GitHubAPIError, KeyError, TypeError, ValueError) as exc:
            logs.append(f"\n=== {name} ===\nLog unavailable: {redact(str(exc))}")
    return names, "\n".join(logs)


def evidence_lines(log_text: str) -> list[str]:
    selected: list[str] = []
    seen: set[str] = set()
    for raw in log_text.splitlines():
        line = raw.strip()
        if not line or len(line) > 500:
            continue
        if not any(pattern.search(line) for pattern in EVIDENCE_PATTERNS):
            continue
        normalized = redact(line)
        if normalized in seen:
            continue
        seen.add(normalized)
        selected.append(normalized)
        if len(selected) >= MAX_EVIDENCE_LINES:
            break
    return selected


def diagnose(
    *, conclusion: str, failed_jobs: Sequence[str], log_text: str
) -> Diagnosis:
    lower = log_text.lower()
    evidence = evidence_lines(log_text)

    if conclusion == "startup_failure":
        return Diagnosis(
            "workflow-startup",
            "The workflow never started",
            (
                "GitHub rejected or could not schedule the workflow before "
                "repository code or tests executed."
            ),
            (
                "Inspect workflow syntax, permissions, Actions settings, billing, "
                "and runner availability."
            ),
            evidence,
            list(failed_jobs),
            False,
        )
    if "forbidden root artifacts" in lower:
        return Diagnosis(
            "repository-cleanliness",
            "A generated or packaged file is committed at repository root",
            "The ecosystem verifier is rejecting a root artifact by design.",
            (
                "Move it to a GitHub Release or Actions artifact, remove it from "
                "Git, and add a narrow ignore rule."
            ),
            evidence,
            list(failed_jobs),
            True,
        )
    if "would reformat" in lower or "black --check" in lower:
        return Diagnosis(
            "formatting",
            "Python formatting does not match the repository standard",
            "Black found deterministic formatting differences.",
            (
                "Run Black on the exact files named in the log and commit only "
                "that formatting."
            ),
            evidence,
            list(failed_jobs),
            True,
        )
    if "resource not accessible" in lower:
        return Diagnosis(
            "permissions",
            "The workflow token lacks a required repository permission",
            "GitHub denied an API operation; this is a workflow permission problem.",
            (
                "Grant only the missing permission in the workflow or repository "
                "Actions settings."
            ),
            evidence,
            list(failed_jobs),
            True,
        )
    if "syntaxerror" in lower or "indentationerror" in lower:
        return Diagnosis(
            "syntax",
            "Source code cannot be parsed",
            "A parser stopped before the test suite could complete.",
            (
                "Repair the first reported file and line, then rerun compilation "
                "and tests."
            ),
            evidence,
            list(failed_jobs),
            True,
        )
    if "modulenotfounderror" in lower or "importerror" in lower:
        return Diagnosis(
            "dependency-or-import",
            "A required module cannot be imported",
            (
                "The clean environment cannot resolve a required dependency or "
                "package path."
            ),
            (
                "Correct the dependency declaration or import path and verify in "
                "a clean environment."
            ),
            evidence,
            list(failed_jobs),
            True,
        )
    if "no space left on device" in lower:
        return Diagnosis(
            "runner-capacity",
            "The runner ran out of storage",
            "This is infrastructure capacity, not a repository code defect.",
            "Clean runner workspaces and caches or move the job to a larger runner.",
            evidence,
            list(failed_jobs),
            False,
        )
    if "pytest" in lower or "assertionerror" in lower or " failed" in lower:
        return Diagnosis(
            "test-failure",
            "One or more repository tests failed",
            (
                "The branch reached the test suite and a contract did not match "
                "the implementation."
            ),
            (
                "Reproduce the first failure, make the smallest repair, rerun the "
                "focused test, then the full suite."
            ),
            evidence,
            list(failed_jobs),
            True,
        )
    return Diagnosis(
        "unclassified-failure",
        "A repository check failed",
        (
            "The doctor collected the failed-job evidence but could not classify "
            "it deterministically."
        ),
        (
            "Use the exact evidence in the Repair Control Plane and publish only "
            "a verified bounded change."
        ),
        evidence,
        list(failed_jobs),
        conclusion not in NON_REPAIRABLE_CONCLUSIONS,
    )


def latest_run_for_pull_request(
    token: str, repository: str, pull_request_number: int
) -> Mapping[str, Any]:
    pull_request = api_json(token, f"/repos/{repository}/pulls/{pull_request_number}")
    head_sha = str((pull_request.get("head") or {}).get("sha") or "")
    if not head_sha:
        raise GitHubAPIError("Pull request does not expose a head revision")
    query = urllib.parse.urlencode(
        {"head_sha": head_sha, "event": "pull_request", "per_page": 100}
    )
    payload = api_json(token, f"/repos/{repository}/actions/runs?{query}")
    runs = [
        item
        for item in payload.get("workflow_runs", [])
        if item.get("name") not in SKIP_WORKFLOWS
        and item.get("status") == "completed"
    ]
    failed = [item for item in runs if item.get("conclusion") != "success"]
    candidates = failed or runs
    if not candidates:
        raise GitHubAPIError(
            "No completed workflow run exists for the pull-request head"
        )
    return candidates[0]


def comments_for_issue(
    token: str, repository: str, issue_number: int
) -> list[Mapping[str, Any]]:
    return list(
        api_json(
            token,
            f"/repos/{repository}/issues/{issue_number}/comments?per_page=100",
        )
    )


def post_or_update_comment(
    token: str, repository: str, pull_request_number: int, body: str
) -> str:
    comments = comments_for_issue(token, repository, pull_request_number)
    existing = next(
        (item for item in comments if COMMENT_MARKER in str(item.get("body") or "")),
        None,
    )
    if existing:
        updated = api_json(
            token,
            f"/repos/{repository}/issues/comments/{int(existing['id'])}",
            method="PATCH",
            payload={"body": body},
        )
        return str(updated.get("html_url") or "")
    created = api_json(
        token,
        f"/repos/{repository}/issues/{pull_request_number}/comments",
        method="POST",
        payload={"body": body},
    )
    return str(created.get("html_url") or "")


def already_dispatched(
    token: str, repository: str, pull_request_number: int | None, run_id: int
) -> bool:
    if pull_request_number is None:
        return False
    marker = f"{RUN_MARKER_PREFIX}{run_id} -->"
    return any(
        marker in str(item.get("body") or "")
        and "Repair requested: `true`" in str(item.get("body") or "")
        for item in comments_for_issue(token, repository, pull_request_number)
    )


def dispatch_repair(
    token: str,
    repository: str,
    *,
    default_branch: str,
    pull_request_number: int | None,
    run: Mapping[str, Any],
    failure_summary: str,
) -> None:
    inputs = {
        "scope": "pull_request" if pull_request_number is not None else "default",
        "pull_request_number": str(pull_request_number or ""),
        "target_sha": str(run.get("head_sha") or ""),
        "source_run_id": str(run.get("id") or ""),
        "source_name": str(run.get("name") or "GitHub Actions"),
        "provider": "github_actions",
        "status_url": str(run.get("html_url") or ""),
        "failure_summary": failure_summary[:MAX_FAILURE_SUMMARY],
    }
    api_json(
        token,
        (
            f"/repos/{repository}/actions/workflows/"
            "amosclaud-repair-control-plane.yml/dispatches"
        ),
        method="POST",
        payload={"ref": default_branch, "inputs": inputs},
    )


def render_comment(result: DoctorResult) -> str:
    diagnosis = result.diagnosis
    lines = [
        COMMENT_MARKER,
        f"{RUN_MARKER_PREFIX}{result.run_id} -->",
        "## Amosclaud Repository Doctor",
        "",
        f"**Status:** `{'green' if result.conclusion == 'success' else 'red'}`",
        f"**Workflow:** `{result.workflow_name}`",
        f"**Run:** `{result.run_id}` (attempt `{result.run_attempt}`)",
        f"**Revision:** `{result.target_sha}`",
        "",
        f"### {diagnosis.title}",
        "",
        diagnosis.explanation,
        "",
        f"**Proposed fix:** {diagnosis.proposed_fix}",
    ]
    if diagnosis.failed_jobs:
        lines.extend(
            [
                "",
                "**Failed jobs:** "
                + ", ".join(f"`{item}`" for item in diagnosis.failed_jobs),
            ]
        )
    if diagnosis.evidence:
        lines.extend(["", "**Evidence:**", "", "```text"])
        lines.extend(diagnosis.evidence)
        lines.append("```")
    lines.extend(["", "### Fix route", ""])
    if result.repair_requested:
        lines.append(
            "The existing bounded **Amosclaud Repair Control Plane** was "
            "dispatched for this exact revision."
        )
    elif result.repair_dispatch_error:
        lines.append(
            "The repair dispatch failed, so no success is claimed: "
            f"`{redact(result.repair_dispatch_error)}`"
        )
    elif result.conclusion == "success":
        lines.append("The watched revision is green. No fixer run was requested.")
    elif not diagnosis.repairable:
        lines.append(
            "No automatic code repair was requested for this failure category."
        )
    else:
        lines.append(
            "Explanation only. Comment `@amosclaud fix` for a bounded repair retry."
        )
    lines.extend(
        [
            "",
            f"Repair requested: `{'true' if result.repair_requested else 'false'}`",
            "",
            (
                "Repository tests run independently. Agent Chat does not cancel, "
                "replace, or mark them successful."
            ),
        ]
    )
    return "\n".join(lines) + "\n"


def write_outputs(values: Mapping[str, str | bool | int]) -> None:
    output_path = os.getenv("GITHUB_OUTPUT")
    if not output_path:
        return
    with Path(output_path).open("a", encoding="utf-8") as handle:
        for key, value in values.items():
            if isinstance(value, bool):
                rendered = "true" if value else "false"
            else:
                rendered = str(value)
            handle.write(f"{key}={rendered}\n")


def run_doctor(
    *,
    token: str,
    repository: str,
    run: Mapping[str, Any],
    dispatch: bool,
    comment: bool,
) -> DoctorResult:
    run_id = int(run.get("id") or 0)
    conclusion = str(run.get("conclusion") or "unknown")
    target_sha = str(run.get("head_sha") or "")
    pull_request_number = pull_request_for_run(token, repository, run)
    failed_jobs, log_text = failed_jobs_and_logs(token, repository, run_id)
    diagnosis = diagnose(
        conclusion=conclusion,
        failed_jobs=failed_jobs,
        log_text=log_text,
    )
    result = DoctorResult(
        workflow_name=str(run.get("name") or "GitHub Actions"),
        conclusion=conclusion,
        run_id=run_id,
        run_attempt=int(run.get("run_attempt") or 1),
        target_sha=target_sha,
        pull_request_number=pull_request_number,
        diagnosis=diagnosis,
    )
    if (
        dispatch
        and conclusion in REPAIRABLE_CONCLUSIONS
        and diagnosis.repairable
        and not already_dispatched(token, repository, pull_request_number, run_id)
    ):
        try:
            dispatch_repair(
                token,
                repository,
                default_branch=repository_default_branch(token, repository),
                pull_request_number=pull_request_number,
                run=run,
                failure_summary=(
                    f"{diagnosis.title}\n{diagnosis.explanation}\n"
                    f"Proposed fix: {diagnosis.proposed_fix}\n"
                    + "\n".join(diagnosis.evidence)
                ),
            )
            result.repair_requested = True
        except GitHubAPIError as exc:
            result.repair_dispatch_error = str(exc)
    if comment and pull_request_number is not None:
        result.comment_url = post_or_update_comment(
            token, repository, pull_request_number, render_comment(result)
        )
    return result


def summarize_sha(
    token: str, repository: str, sha: str
) -> tuple[bool, list[str], list[str]]:
    checks = api_json(
        token,
        (
            f"/repos/{repository}/commits/{urllib.parse.quote(sha)}"
            "/check-runs?per_page=100"
        ),
    ).get("check_runs", [])
    relevant = [item for item in checks if item.get("name") not in SKIP_WORKFLOWS]
    pending = [
        str(item.get("name") or "unknown")
        for item in relevant
        if item.get("status") != "completed"
    ]
    failing = [
        str(item.get("name") or "unknown")
        for item in relevant
        if item.get("status") == "completed"
        and item.get("conclusion") not in {"success", "neutral", "skipped"}
    ]
    return bool(relevant) and not pending and not failing, failing, pending


def green_comment(sha: str) -> str:
    return "\n".join(
        [
            COMMENT_MARKER,
            "## Amosclaud Repository Doctor",
            "",
            "**Status:** `green`",
            f"**Revision:** `{sha}`",
            "",
            (
                "All currently reported GitHub check runs for this revision "
                "completed without a failing conclusion."
            ),
            "",
            "No fixer run is required. Repository tests remain the source of truth.",
        ]
    ) + "\n"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices={"run", "pr", "result"})
    parser.add_argument("--repository", required=True)
    parser.add_argument("--run-id", type=int, default=0)
    parser.add_argument("--pull-request", type=int, default=0)
    parser.add_argument("--sha", default="")
    parser.add_argument("--dispatch", action="store_true")
    parser.add_argument("--no-comment", action="store_true")
    parser.add_argument("--output", required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if not token:
        raise SystemExit("GITHUB_TOKEN is required")
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if args.command == "result":
        sha = args.sha.strip()
        if not sha:
            raise SystemExit("--sha is required for result mode")
        all_green, failing, pending = summarize_sha(token, args.repository, sha)
        pull_request_number = pull_request_for_sha(token, args.repository, sha)
        payload = {
            "sha": sha,
            "all_green": all_green,
            "failing": failing,
            "pending": pending,
            "pull_request_number": pull_request_number,
        }
        if all_green and pull_request_number is not None and not args.no_comment:
            payload["comment_url"] = post_or_update_comment(
                token, args.repository, pull_request_number, green_comment(sha)
            )
        output_path.write_text(
            json.dumps(payload, indent=2) + "\n", encoding="utf-8"
        )
        write_outputs(
            {
                "all_green": all_green,
                "pull_request_number": pull_request_number or "",
            }
        )
        return 0

    if args.command == "run":
        if not args.run_id:
            raise SystemExit("--run-id is required for run mode")
        run = api_json(token, f"/repos/{args.repository}/actions/runs/{args.run_id}")
    else:
        if not args.pull_request:
            raise SystemExit("--pull-request is required for pr mode")
        run = latest_run_for_pull_request(token, args.repository, args.pull_request)

    result = run_doctor(
        token=token,
        repository=args.repository,
        run=run,
        dispatch=args.dispatch,
        comment=not args.no_comment,
    )
    output_path.write_text(
        json.dumps(asdict(result), indent=2) + "\n", encoding="utf-8"
    )
    write_outputs(
        {
            "pull_request_number": result.pull_request_number or "",
            "target_sha": result.target_sha,
            "repairable": result.diagnosis.repairable,
            "repair_requested": result.repair_requested,
            "conclusion": result.conclusion,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

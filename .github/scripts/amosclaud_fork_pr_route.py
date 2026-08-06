#!/usr/bin/env python3
"""Resolve failed fork PRs without exposing repair credentials to fork code."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from amosclaud_bot.approval_gate import (
    APPROVAL_CONSUMED_MARKER,
    APPROVAL_MARKER,
    APPROVAL_RECORD_MARKER,
)
from amosclaud_bot.approval_gate_v2 import _high_risk_files

FAILURE_CONCLUSIONS = {"failure", "timed_out", "action_required", "startup_failure"}
TRUSTED_BOT_LOGINS = {"github-actions[bot]"}


def request_json(
    method: str,
    url: str,
    *,
    token: str,
    payload: dict[str, Any] | None = None,
) -> Any:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "Amosclaud-Fork-Repair/1.0",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = response.read()
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"GitHub API {method} {url} failed: HTTP {error.code}: {detail}"
        ) from error
    if not body:
        return None
    return json.loads(body.decode("utf-8"))


def api(repository: str, suffix: str) -> str:
    return f"https://api.github.com/repos/{repository}{suffix}"


def open_pull_request_for_sha(
    repository: str,
    sha: str,
    token: str,
) -> dict[str, Any] | None:
    pulls = request_json(
        "GET",
        api(repository, f"/commits/{sha}/pulls"),
        token=token,
    )
    for pull in pulls or []:
        if pull.get("state") == "open":
            return pull
    return None


def pull_request_files(
    repository: str,
    number: int,
    token: str,
) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    for page in range(1, 51):
        result = request_json(
            "GET",
            api(repository, f"/pulls/{number}/files?per_page=100&page={page}"),
            token=token,
        )
        if not isinstance(result, list):
            return []
        files.extend(item for item in result if isinstance(item, dict))
        if len(result) < 100:
            return files
    return files


def approval_issue(
    repository: str,
    number: int,
    token: str,
) -> dict[str, Any] | None:
    marker = f"{APPROVAL_MARKER}pull-request-{number} -->"
    for page in range(1, 11):
        issues = request_json(
            "GET",
            api(repository, f"/issues?state=all&per_page=100&page={page}"),
            token=token,
        )
        if not isinstance(issues, list):
            return None
        for issue in issues:
            if issue.get("pull_request"):
                continue
            if marker in str(issue.get("body") or ""):
                return issue
        if len(issues) < 100:
            break
    return None


def sensitive_approval_state(
    repository: str,
    number: int,
    token: str,
) -> tuple[bool, str]:
    issue = approval_issue(repository, number, token)
    if issue is None:
        return False, ""
    issue_number = issue.get("number")
    if not isinstance(issue_number, int):
        return False, ""

    approved = False
    consumed = False
    for page in range(1, 51):
        comments = request_json(
            "GET",
            api(
                repository,
                f"/issues/{issue_number}/comments?per_page=100&page={page}",
            ),
            token=token,
        )
        if not isinstance(comments, list):
            return False, str(issue_number)
        for comment in comments:
            user = comment.get("user") or {}
            login = str(user.get("login") or "").lower()
            user_type = str(user.get("type") or "").lower()
            if login not in TRUSTED_BOT_LOGINS or user_type != "bot":
                continue
            body = str(comment.get("body") or "")
            if APPROVAL_CONSUMED_MARKER in body:
                consumed = True
            if APPROVAL_RECORD_MARKER in body and "**Decision:** **APPROVED**" in body:
                approved = True
        if len(comments) < 100:
            break
    return approved and not consumed, str(issue_number)


def write_outputs(values: dict[str, Any]) -> None:
    output_path = os.getenv("GITHUB_OUTPUT")
    lines = []
    for key, value in values.items():
        if isinstance(value, bool):
            rendered = "true" if value else "false"
        else:
            rendered = str(value)
        lines.append(f"{key}={rendered}")
    text = "\n".join(lines) + "\n"
    if output_path:
        Path(output_path).open("a", encoding="utf-8").write(text)
    else:
        print(text, end="")


def resolve(args: argparse.Namespace) -> int:
    event = json.loads(Path(args.event_path).read_text(encoding="utf-8"))
    run = event.get("workflow_run") or {}
    conclusion = str(run.get("conclusion") or "")
    source = str(run.get("name") or "unknown workflow")
    source_run_id = str(run.get("id") or "")
    status_url = str(run.get("html_url") or "")
    sha = str(run.get("head_sha") or "")

    if args.pull_request_number:
        pull = request_json(
            "GET",
            api(args.repository, f"/pulls/{args.pull_request_number}"),
            token=args.token,
        )
        conclusion = "failure"
        source = args.source_name or "manual fork PR repair"
    else:
        if conclusion not in FAILURE_CONCLUSIONS:
            write_outputs(
                {
                    "should_repair": False,
                    "reason": f"workflow conclusion {conclusion!r} is not repairable",
                }
            )
            return 0
        pull = open_pull_request_for_sha(args.repository, sha, args.token)

    if not isinstance(pull, dict) or pull.get("state") != "open":
        write_outputs(
            {
                "should_repair": False,
                "reason": "no open pull request resolved for the failed revision",
            }
        )
        return 0

    number = int(pull["number"])
    head = pull.get("head") or {}
    base = pull.get("base") or {}
    head_repository = str((head.get("repo") or {}).get("full_name") or "")
    head_sha = str(head.get("sha") or sha)
    head_ref = str(head.get("ref") or "")
    base_ref = str(base.get("ref") or "main")

    if not head_repository or head_repository == args.repository:
        write_outputs(
            {
                "should_repair": False,
                "reason": "same-repository PR is handled by the main repair control plane",
                "pull_request_number": number,
            }
        )
        return 0

    files = pull_request_files(args.repository, number, args.token)
    sensitive = _high_risk_files(files)
    approval_granted, approval_number = sensitive_approval_state(
        args.repository,
        number,
        args.token,
    )
    if sensitive and not approval_granted:
        write_outputs(
            {
                "should_repair": False,
                "requires_approval": True,
                "reason": "environment, secret-bearing, or personal-information content requires approval",
                "pull_request_number": number,
                "approval_issue_number": approval_number,
                "sensitive_files": ",".join(sensitive[:12]),
            }
        )
        return 0

    fingerprint = hashlib.sha256(
        f"{args.repository}|{number}|{head_sha}|{source}".encode("utf-8")
    ).hexdigest()[:20]
    write_outputs(
        {
            "should_repair": True,
            "requires_approval": False,
            "sensitive_approved": bool(sensitive and approval_granted),
            "approval_issue_number": approval_number,
            "pull_request_number": number,
            "head_repository": head_repository,
            "head_sha": head_sha,
            "head_ref": head_ref,
            "base_ref": base_ref,
            "source_run_id": source_run_id,
            "source_name": source,
            "status_url": status_url,
            "fingerprint": fingerprint,
            "reason": "fork PR failure is eligible for verified repair",
        }
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event-path", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--pull-request-number", default="")
    parser.add_argument("--source-name", default="")
    args = parser.parse_args()
    return resolve(args)


if __name__ == "__main__":
    raise SystemExit(main())

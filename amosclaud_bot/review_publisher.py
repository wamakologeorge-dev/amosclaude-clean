from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from .bot import AmosclaudBot, parse_command
from .professional import _professional_review

_PAGE_SIZE = 100
_MAX_PAGES = 100
_BLOCKING_CONCLUSIONS = {
    "action_required",
    "cancelled",
    "failure",
    "startup_failure",
    "stale",
    "timed_out",
}
_PENDING_STATUSES = {"in_progress", "pending", "queued", "requested", "waiting"}
_SECURITY_CHECK_HINTS = (
    "codeql",
    "security",
    "dependency threat",
    "dependency review",
    "fortify",
    "secret scanning",
    "secret protection",
)


@dataclass(frozen=True)
class ReviewPublication:
    applicable: bool
    submitted: bool
    status: str
    pull_number: int | None = None
    commit_sha: str | None = None


def _pull_files(bot: AmosclaudBot, number: int) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    for page in range(1, _MAX_PAGES + 1):
        query = urlencode({"per_page": _PAGE_SIZE, "page": page})
        batch = bot._request(
            "GET",
            f"/repos/{bot.repository}/pulls/{number}/files?{query}",
        )
        if not isinstance(batch, list):
            break
        files.extend(item for item in batch if isinstance(item, dict))
        if len(batch) < _PAGE_SIZE:
            break
    return files


def _check_runs(bot: AmosclaudBot, head_sha: str) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for page in range(1, _MAX_PAGES + 1):
        query = urlencode({"per_page": _PAGE_SIZE, "page": page})
        payload = bot._request(
            "GET",
            f"/repos/{bot.repository}/commits/{head_sha}/check-runs?{query}",
        )
        batch = payload.get("check_runs", []) if isinstance(payload, dict) else []
        if not isinstance(batch, list):
            break
        checks.extend(item for item in batch if isinstance(item, dict))
        if len(batch) < _PAGE_SIZE:
            break
    return checks


def _blocking_checks(checks: list[dict[str, Any]]) -> list[str]:
    return [
        str(check.get("name") or "unnamed check")
        for check in checks
        if str(check.get("conclusion") or "").lower() in _BLOCKING_CONCLUSIONS
    ]


def _pending_checks(checks: list[dict[str, Any]]) -> list[str]:
    pending: list[str] = []
    for check in checks:
        name = str(check.get("name") or "unnamed check")
        status = str(check.get("status") or "").lower()
        conclusion = str(check.get("conclusion") or "").lower()
        if status in _PENDING_STATUSES or not conclusion:
            pending.append(name)
    return pending


def _security_blockers(checks: list[dict[str, Any]]) -> list[str]:
    return [
        name
        for name in _blocking_checks(checks)
        if any(hint in name.lower() for hint in _SECURITY_CHECK_HINTS)
    ]


def _check_summary(checks: list[dict[str, Any]]) -> str:
    blocking = _blocking_checks(checks)
    pending = _pending_checks(checks)
    passing = 0
    for check in checks:
        conclusion = str(check.get("conclusion") or "").lower()
        if conclusion in {"success", "neutral", "skipped"}:
            passing += 1

    lines = [
        "## Exact-commit check evidence",
        f"- Checks observed: {len(checks)}",
        f"- Passing/neutral/skipped: {passing}",
        f"- Blocking: {len(blocking)}",
        f"- Pending: {len(pending)}",
    ]
    if blocking:
        lines.append("- Blocking checks: " + ", ".join(blocking[:10]))
    if pending:
        lines.append("- Pending checks: " + ", ".join(pending[:10]))
    return "\n".join(lines)


def _review_body(
    *,
    pr: dict[str, Any],
    files: list[dict[str, Any]],
    checks: list[dict[str, Any]],
    head_sha: str,
) -> str:
    base = _professional_review(
        pr=pr,
        files=files,
        autonomous_result={
            "status": "completed",
            "evidence": [
                "Trusted default-branch review runtime used.",
                f"All {len(files)} changed file record(s) were fetched through the GitHub API.",
                "Pull-request code was not executed and no repository write was attempted.",
            ],
        },
    )

    # This reviewer currently analyzes changed-file metadata and exact-commit checks,
    # not complete patch semantics. It must never claim a correctness approval.
    base = base.replace("**APPROVE**", "**NEEDS HUMAN REVIEW**")
    blocking = _blocking_checks(checks)
    pending = _pending_checks(checks)
    security_blockers = _security_blockers(checks)
    if blocking or pending:
        base = base.replace("**NEEDS HUMAN REVIEW**", "**CHANGES REQUESTED**")
    if security_blockers:
        base = base.replace("**Risk:** **LOW**", "**Risk:** **HIGH**")
        base = base.replace("**Risk:** **MEDIUM**", "**Risk:** **HIGH**")

    security_verdict = (
        "## Security threat verdict\n"
        "**BLOCKED — CHANGES REQUIRED**\n"
        "- Failing security checks: " + ", ".join(f"`{name}`" for name in security_blockers[:10])
        if security_blockers
        else "## Security threat verdict\n**NO FAILING SECURITY CHECK OBSERVED**"
    )
    coverage = (
        "## Content-review coverage\n"
        "**METADATA AND CHECK EVIDENCE ONLY**\n"
        "- Changed-file names and size statistics were inspected.\n"
        "- Complete patch semantics were not analyzed by this review path.\n"
        "- A human or a future content-aware reviewer must confirm correctness."
    )
    notice = (
        "\n\n## Review authority\n"
        "- This is an automated, read-only, non-blocking `COMMENT` review.\n"
        "- Amosclaud Bot does not approve, request changes through GitHub authority, merge, or push.\n"
        f"- Exact reviewed commit: `{head_sha}`\n\n"
        f"{coverage}\n\n"
        f"{security_verdict}\n\n"
        f"{_check_summary(checks)}"
    )
    return (base[: 10000 - len(notice)] + notice)[:10000]


def publish_review(
    bot: AmosclaudBot,
    payload: dict[str, Any],
) -> ReviewPublication:
    comment = payload.get("comment") or {}
    command, objective = parse_command(str(comment.get("body") or ""))
    issue = payload.get("issue") or {}
    number = issue.get("number")
    if command != "review" or not issue.get("pull_request") or not isinstance(number, int):
        return ReviewPublication(False, False, "NOT_APPLICABLE")

    pr = bot._request("GET", f"/repos/{bot.repository}/pulls/{number}")
    head_sha = str(((pr or {}).get("head") or {}).get("sha") or "").strip()
    if not head_sha:
        bot.post_comment(
            number,
            "### Amosclaud Bot — Review not submitted\n\n"
            "The pull request's exact head commit could not be resolved, so no review claim was published.",
        )
        return ReviewPublication(True, False, "HEAD_UNRESOLVED", number)

    files = _pull_files(bot, number)
    checks = _check_runs(bot, head_sha)
    latest = bot._request("GET", f"/repos/{bot.repository}/pulls/{number}")
    latest_sha = str(((latest or {}).get("head") or {}).get("sha") or "").strip()
    if latest_sha != head_sha:
        bot.post_comment(
            number,
            "### Amosclaud Bot — Review safely deferred\n\n"
            f"The pull-request head changed from `{head_sha[:12]}` to "
            f"`{latest_sha[:12] or 'unresolved'}` during analysis. No stale formal review was submitted. "
            "Run `@amosclaud review` again on the current head.",
        )
        return ReviewPublication(True, False, "HEAD_CHANGED", number, head_sha)

    review_objective = (
        objective
        or f"Review pull request #{number} for correctness, tests, security, and merge risk"
    )
    pr = dict(pr) if isinstance(pr, dict) else {}
    pr["amosclaud_review_objective"] = review_objective
    body = _review_body(pr=pr, files=files, checks=checks, head_sha=head_sha)
    bot._request(
        "POST",
        f"/repos/{bot.repository}/pulls/{number}/reviews",
        {
            "body": body,
            "event": "COMMENT",
            "commit_id": head_sha,
        },
    )
    return ReviewPublication(True, True, "SUBMITTED", number, head_sha)


def run_from_environment() -> int:
    event_name = os.getenv("GITHUB_EVENT_NAME", "")
    event_path = os.getenv("GITHUB_EVENT_PATH", "")
    repository = os.getenv("GITHUB_REPOSITORY", "")
    token = os.getenv("GITHUB_TOKEN", "")
    if event_name != "issue_comment":
        return 0
    if not event_path or not repository or not token:
        raise RuntimeError("GITHUB_EVENT_PATH, GITHUB_REPOSITORY, and GITHUB_TOKEN are required")

    payload = json.loads(Path(event_path).read_text(encoding="utf-8"))
    bot = AmosclaudBot(repository=repository, token=token, workspace=Path.cwd())
    result = publish_review(bot, payload)
    print(json.dumps(result.__dict__, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(run_from_environment())

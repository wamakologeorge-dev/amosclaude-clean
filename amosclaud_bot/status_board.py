from __future__ import annotations

from typing import Any

from amoscloud_ai.health_contract import evaluate_health

from .bot import AmosclaudBot

_STATUS_REQUESTS = {
    "@amosclaud status",
    "@amosclaud-bot status",
    "@amosclaud-status",
    "amosclaud-status",
}
_EXPECTED_SKIP_PATTERNS = (
    "*Fork PR Fixer*",
    "*PR Repair Callback*",
    "*Model Agent*",
    "*cmood Autonomous Agent Trigger*",
    "*Autonomous Background Engineer*",
    "Amosclaud Agent Main",
    "Amosclaud Repair Results",
    ".github/workflows/main.yml",
    ".github/workflows/results.yml",
)


def is_status_request(text: str) -> bool:
    normalized = " ".join((text or "").strip().lower().split())
    return normalized in _STATUS_REQUESTS


def _latest_unique_runs(runs: list[dict[str, Any]], limit: int = 20) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for run in runs:
        name = str(run.get("name") or "GitHub Actions")
        if name in seen:
            continue
        seen.add(name)
        selected.append(run)
        if len(selected) >= limit:
            break
    return selected


def _target(bot: AmosclaudBot, payload: dict[str, Any]) -> tuple[str | None, str | None]:
    issue = payload.get("issue") or {}
    issue_number = issue.get("number")

    if issue.get("pull_request") and isinstance(issue_number, int):
        pr = bot._request("GET", f"/repos/{bot.repository}/pulls/{issue_number}")
        if isinstance(pr, dict):
            head = pr.get("head") or {}
            branch = str(head.get("ref") or "") or None
            head_sha = str(head.get("sha") or "") or None
            return branch, head_sha
        return None, None

    repo = bot._request("GET", f"/repos/{bot.repository}")
    branch = str(repo.get("default_branch") or "") if isinstance(repo, dict) else ""
    if not branch:
        return None, None

    branch_data = bot._request("GET", f"/repos/{bot.repository}/branches/{branch}")
    commit = branch_data.get("commit") or {} if isinstance(branch_data, dict) else {}
    head_sha = str(commit.get("sha") or "") or None
    return branch, head_sha


def _workflow_checks(runs: list[dict[str, Any]]) -> list[dict[str, object]]:
    return [
        {
            "name": str(run.get("name") or "GitHub Actions"),
            "status": str(run.get("status") or ""),
            "conclusion": run.get("conclusion"),
        }
        for run in runs
    ]


def build_status_board(bot: AmosclaudBot, payload: dict[str, Any]) -> str:
    branch, head_sha = _target(bot, payload)

    if head_sha:
        endpoint = f"/repos/{bot.repository}/actions/runs?head_sha={head_sha}&per_page=100"
    elif branch:
        endpoint = f"/repos/{bot.repository}/actions/runs?branch={branch}&per_page=100"
    else:
        endpoint = f"/repos/{bot.repository}/actions/runs?per_page=100"

    data = bot._request("GET", endpoint)
    runs = data.get("workflow_runs", []) if isinstance(data, dict) else []
    runs = runs if isinstance(runs, list) else []
    latest = _latest_unique_runs(runs)

    target = branch or (head_sha[:7] if head_sha else "repository")
    commit_label = head_sha[:12] if head_sha else "unresolved"
    if not latest:
        return (
            "### Amosclaud — Verified Workflow Health\n\n"
            "⬜ No GitHub Actions results were found for the exact target commit.\n\n"
            "**Overall:** ⬜ INCOMPLETE\n"
            "**Observed verification:** 0%\n"
            f"**Target:** `{target}`\n"
            f"**Commit:** `{commit_label}`"
        )

    checks = _workflow_checks(latest)
    required = tuple(str(check["name"]) for check in checks)
    result = evaluate_health(
        checks,
        required=required,
        expected_skips=_EXPECTED_SKIP_PATTERNS,
    )

    lines = ["### Amosclaud — Verified Workflow Health", ""]
    markers = {
        "PASSED": "🟩",
        "EXPECTED_SKIP": "⬜",
        "PENDING": "🟨",
        "FAILED": "🟥",
        "MISSING": "🟥",
        "UNEXPECTED_SKIP": "🟥",
        "UNKNOWN": "🟥",
    }
    for check in result["checks"]:
        state = str(check["state"])
        marker = markers.get(state, "⬜")
        lines.append(f"{marker} **{check['name']}** — {state}")

    overall = str(result["overall"])
    overall_label = {
        "VERIFIED": "🟩 VERIFIED",
        "PENDING": "🟨 PENDING",
        "ACTION_NEEDED": "🟥 ACTION NEEDED",
        "INCOMPLETE": "⬜ INCOMPLETE",
    }.get(overall, "⬜ INCOMPLETE")
    lines.extend(
        [
            "",
            f"**Overall:** {overall_label}",
            f"**Observed verification:** {result['percentage']}%",
            f"**Target:** `{target}`",
            f"**Commit:** `{commit_label}`",
            "",
            "100% is shown only when every observed workflow for this exact commit "
            "has passed or is a declared conditional skip.",
        ]
    )
    return "\n".join(lines)[:2400]


def handle_status_request(bot: AmosclaudBot, payload: dict[str, Any]) -> int | None:
    comment = payload.get("comment") or {}
    if not is_status_request(str(comment.get("body") or "")):
        return None

    issue = payload.get("issue") or {}
    number = issue.get("number")
    if not isinstance(number, int):
        return 0

    bot.post_comment(number, build_status_board(bot, payload))
    return 0

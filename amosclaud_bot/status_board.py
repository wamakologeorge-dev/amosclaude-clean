from __future__ import annotations

from typing import Any

from .bot import AmosclaudBot

_STATUS_REQUESTS = {
    "@amosclaud status",
    "@amosclaud-bot status",
    "@amosclaud-status",
    "amosclaud-status",
}


def is_status_request(text: str) -> bool:
    normalized = " ".join((text or "").strip().lower().split())
    return normalized in _STATUS_REQUESTS


def _run_state(run: dict[str, Any]) -> tuple[str, str]:
    status = str(run.get("status") or "").lower()
    conclusion = str(run.get("conclusion") or "").lower()

    if status != "completed":
        return "🟨", "RUNNING"
    if conclusion == "success":
        return "🟩", "PASSED"
    if conclusion in {"neutral", "skipped"}:
        return "⬜", conclusion.upper()
    if conclusion in {"cancelled", "stale"}:
        return "⬜", conclusion.upper()
    return "🟥", "FAILED"


def _latest_unique_runs(runs: list[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
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


def build_status_board(bot: AmosclaudBot, payload: dict[str, Any]) -> str:
    issue = payload.get("issue") or {}
    issue_number = issue.get("number")

    branch: str | None = None
    head_sha: str | None = None

    if issue.get("pull_request") and isinstance(issue_number, int):
        pr = bot._request("GET", f"/repos/{bot.repository}/pulls/{issue_number}")
        if isinstance(pr, dict):
            head = pr.get("head") or {}
            branch = str(head.get("ref") or "") or None
            head_sha = str(head.get("sha") or "") or None
    else:
        repo = bot._request("GET", f"/repos/{bot.repository}")
        if isinstance(repo, dict):
            branch = str(repo.get("default_branch") or "") or None

    if head_sha:
        endpoint = f"/repos/{bot.repository}/actions/runs?head_sha={head_sha}&per_page=50"
    elif branch:
        endpoint = f"/repos/{bot.repository}/actions/runs?branch={branch}&per_page=50"
    else:
        endpoint = f"/repos/{bot.repository}/actions/runs?per_page=50"

    data = bot._request("GET", endpoint)
    runs = data.get("workflow_runs", []) if isinstance(data, dict) else []
    runs = runs if isinstance(runs, list) else []
    latest = _latest_unique_runs(runs)

    if not latest:
        return "### Amosclaud — Workflow Status\n\n⬜ No GitHub Actions results found for this target."

    lines = ["### Amosclaud — Workflow Status", ""]
    has_failure = False
    has_running = False
    for run in latest:
        icon, state = _run_state(run)
        name = str(run.get("name") or "GitHub Actions")
        lines.append(f"{icon} **{name}** — {state}")
        has_failure = has_failure or state == "FAILED"
        has_running = has_running or state == "RUNNING"

    if has_failure:
        overall = "🟥 ACTION NEEDED"
    elif has_running:
        overall = "🟨 RUNNING"
    else:
        overall = "🟩 READY"

    lines.extend(["", f"**Overall:** {overall}"])
    target = branch or (head_sha[:7] if head_sha else "repository")
    lines.append(f"**Target:** `{target}`")
    return "\n".join(lines)[:1800]


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

from __future__ import annotations

from typing import Any
from urllib.parse import quote, urlencode

from amoscloud_ai.health_contract import evaluate_health

from .bot import AmosclaudBot

_STATUS_REQUESTS = {
    "@amosclaud status",
    "@amosclaud-bot status",
    "@amosclaud-status",
    "amosclaud-status",
}
_EXPECTED_SKIP_EVENTS: tuple[tuple[str, frozenset[str]], ...] = (
    ("*Fork PR Fixer*", frozenset({"pull_request", "workflow_run"})),
    ("*PR Repair Callback*", frozenset({"workflow_run"})),
    ("*cmood Autonomous Agent Trigger*", frozenset({"issue_comment"})),
    ("Amosclaud Agent Main", frozenset({"workflow_run"})),
    ("Amosclaud Repair Results", frozenset({"workflow_run"})),
    (".github/workflows/main.yml", frozenset({"workflow_run"})),
    (".github/workflows/results.yml", frozenset({"workflow_run"})),
)
_REQUIRED_PULL_REQUEST_WORKFLOWS = (
    "Fast PR Gate",
    "Amosclaud Workflow Policy",
    "Build and Verify",
    "Amosclaud CI",
    "CodeQL",
    "Amosclaud Dependency Threat Gate",
    "Fortify AST Scan",
)
_REQUIRED_DEFAULT_BRANCH_WORKFLOWS = (
    "Build and Verify",
    "Amosclaud CI",
    "CodeQL",
    "Fortify AST Scan",
)
_MAX_PAGES = 100
_PAGE_SIZE = 100
_VISIBLE_CHECK_LIMIT = 24


def is_status_request(text: str) -> bool:
    normalized = " ".join((text or "").strip().lower().split())
    return normalized in _STATUS_REQUESTS


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

    encoded_branch = quote(branch, safe="")
    branch_data = bot._request("GET", f"/repos/{bot.repository}/branches/{encoded_branch}")
    commit = branch_data.get("commit") or {} if isinstance(branch_data, dict) else {}
    head_sha = str(commit.get("sha") or "") or None
    return branch, head_sha


def _expected_skip(name: str, event: str) -> bool:
    from fnmatch import fnmatchcase

    normalized_event = event.strip().lower()
    return any(
        fnmatchcase(name, pattern) and normalized_event in allowed_events
        for pattern, allowed_events in _EXPECTED_SKIP_EVENTS
    )


def _exact_commit_runs(bot: AmosclaudBot, head_sha: str) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    for page in range(1, _MAX_PAGES + 1):
        query = urlencode(
            {
                "head_sha": head_sha,
                "per_page": _PAGE_SIZE,
                "page": page,
            }
        )
        endpoint = f"/repos/{bot.repository}/actions/runs?{query}"
        data = bot._request("GET", endpoint)
        batch = data.get("workflow_runs", []) if isinstance(data, dict) else []
        if not isinstance(batch, list):
            break
        runs.extend(run for run in batch if isinstance(run, dict))
        if len(batch) < _PAGE_SIZE:
            break
    return runs


def _workflow_checks(runs: list[dict[str, Any]]) -> list[dict[str, object]]:
    checks: list[dict[str, object]] = []
    for index, run in enumerate(runs, start=1):
        display_name = str(run.get("name") or "GitHub Actions")
        event = str(run.get("event") or "").strip().lower()
        run_id = str(run.get("id") or f"position-{index}")
        checks.append(
            {
                "name": f"{display_name} [run {run_id}]",
                "display_name": display_name,
                "status": str(run.get("status") or ""),
                "conclusion": run.get("conclusion"),
                "event": event,
                "skip_expected": _expected_skip(display_name, event),
            }
        )
    return checks


def _required_keys(
    checks: list[dict[str, object]],
    *,
    required_workflows: tuple[str, ...],
) -> tuple[str, ...]:
    keys = [str(check["name"]) for check in checks]
    observed_names = {str(check.get("display_name") or "") for check in checks}
    for workflow in required_workflows:
        if workflow not in observed_names:
            keys.append(f"{workflow} [required workflow]")
    return tuple(keys)


def _incomplete_board(branch: str | None, reason: str) -> str:
    target = branch or "repository"
    return (
        "### Amosclaud — Verified Workflow Health\n\n"
        f"⬜ {reason}\n\n"
        "**Overall:** ⬜ INCOMPLETE\n"
        "**Observed verification:** 0%\n"
        f"**Target:** `{target}`\n"
        "**Commit:** `unresolved`"
    )


def build_status_board(bot: AmosclaudBot, payload: dict[str, Any]) -> str:
    branch, head_sha = _target(bot, payload)
    if not head_sha:
        return _incomplete_board(
            branch,
            "The exact target commit could not be resolved; branch history was not used.",
        )

    runs = _exact_commit_runs(bot, head_sha)
    target = branch or head_sha[:7]
    commit_label = head_sha[:12]
    if not runs:
        return (
            "### Amosclaud — Verified Workflow Health\n\n"
            "⬜ No GitHub Actions results were found for the exact target commit.\n\n"
            "**Overall:** ⬜ INCOMPLETE\n"
            "**Observed verification:** 0%\n"
            f"**Target:** `{target}`\n"
            f"**Commit:** `{commit_label}`"
        )

    checks = _workflow_checks(runs)
    issue = payload.get("issue") or {}
    required_workflows = (
        _REQUIRED_PULL_REQUEST_WORKFLOWS
        if issue.get("pull_request")
        else _REQUIRED_DEFAULT_BRANCH_WORKFLOWS
    )
    required = _required_keys(checks, required_workflows=required_workflows)
    result = evaluate_health(checks, required=required)
    overall = str(result["overall"])
    overall_label = {
        "VERIFIED": "🟩 VERIFIED",
        "PENDING": "🟨 PENDING",
        "ACTION_NEEDED": "🟥 ACTION NEEDED",
        "INCOMPLETE": "⬜ INCOMPLETE",
    }.get(overall, "⬜ INCOMPLETE")

    lines = [
        "### Amosclaud — Verified Workflow Health",
        "",
        f"**Overall:** {overall_label}",
        f"**Observed verification:** {result['percentage']}%",
        f"**Runs evaluated:** {len(runs)}",
        f"**Contract checks evaluated:** {result['observed_total']}",
        f"**Target:** `{target}`",
        f"**Commit:** `{commit_label}`",
        "",
    ]
    markers = {
        "PASSED": "🟩",
        "EXPECTED_SKIP": "⬜",
        "PENDING": "🟨",
        "FAILED": "🟥",
        "MISSING": "🟥",
        "UNEXPECTED_SKIP": "🟥",
        "UNKNOWN": "🟥",
    }
    visible_checks = result["checks"][:_VISIBLE_CHECK_LIMIT]
    for check in visible_checks:
        state = str(check["state"])
        marker = markers.get(state, "⬜")
        display_name = check.get("display_name") or check["name"]
        lines.append(f"{marker} **{display_name}** — {state}")
    omitted = len(result["checks"]) - len(visible_checks)
    if omitted > 0:
        lines.append(f"⬜ **{omitted} additional contract check(s)** — evaluated but hidden")

    lines.extend(
        [
            "",
            "100% is shown only when every configured required workflow is present "
            "and every observed run for this exact commit passed or was an "
            "event-specific declared conditional skip.",
        ]
    )
    return "\n".join(lines)[:4000]


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

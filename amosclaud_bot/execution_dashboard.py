from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Any

from .bot import AmosclaudBot

DASHBOARD_MARKER = "<!-- amosclaud-live-execution-dashboard -->"
STAGES = ("analyze", "plan", "edit", "test", "verify", "publish")
STAGE_LABELS = {
    "analyze": "Repository analysis",
    "plan": "Execution plan",
    "edit": "Repository changes",
    "test": "Test suite",
    "verify": "Verification",
    "publish": "Commit & pull request",
}
STAGE_SHORT_LABELS = {
    "analyze": "Analyze",
    "plan": "Plan",
    "edit": "Edit",
    "test": "Test",
    "verify": "Verify",
    "publish": "Publish",
}


@dataclass(frozen=True)
class TestCard:
    name: str
    status: str
    detail: str = ""


def _safe(value: str, *, strip_backticks: bool = False) -> str:
    text = str(value or "")
    if strip_backticks:
        text = text.replace("`", "")
    return escape(text, quote=False)


def _icon(status: str) -> str:
    return {
        "passed": "🟩",
        "running": "🟨",
        "failed": "🟥",
        "skipped": "⬜",
        "pending": "⬜",
    }.get(status.lower(), "⬜")


def _stage_status(stage: str, current: str, outcome: str) -> str:
    stage_index = STAGES.index(stage)
    current_index = STAGES.index(current)
    if outcome == "failed" and stage == current:
        return "failed"
    if stage_index < current_index:
        return "passed"
    if stage == current:
        return "passed" if outcome == "passed" else "running"
    return "pending"


def _progress(current_stage: str, outcome: str) -> int:
    completed = sum(
        1
        for stage in STAGES
        if _stage_status(stage, current_stage, outcome) == "passed"
    )
    progress = round((completed / len(STAGES)) * 100)
    if outcome == "running":
        progress = max(
            progress,
            round((STAGES.index(current_stage) + 0.5) / len(STAGES) * 100),
        )
    return progress


def _progress_bar(progress: int, width: int = 12) -> str:
    filled = min(width, max(0, round(progress / 100 * width)))
    return "█" * filled + "░" * (width - filled)


def _result_label(outcome: str) -> str:
    return {
        "passed": "🟩 VERIFIED",
        "failed": "🟥 FAILED",
        "running": "🟨 RUNNING",
    }[outcome]


def _test_summary(tests: list[TestCard]) -> str:
    if not tests:
        return "Not started"
    counts = {"passed": 0, "running": 0, "failed": 0, "pending": 0}
    for card in tests:
        status = card.status.lower()
        counts[status if status in counts else "pending"] += 1
    return " · ".join(
        f"{counts[status]} {status}"
        for status in ("passed", "running", "failed", "pending")
        if counts[status]
    )


def _stage_badges(current_stage: str, outcome: str) -> str:
    return " → ".join(
        f"<kbd>{_icon(_stage_status(stage, current_stage, outcome))} "
        f"{_safe(STAGE_SHORT_LABELS[stage])}</kbd>"
        for stage in STAGES
    )


def _render_3d_card(
    *,
    objective: str,
    current_stage: str,
    outcome: str,
    progress: int,
    files: list[str],
    tests: list[TestCard],
    commit: str,
    pull_request: str,
    branch: str,
) -> list[str]:
    delivery = "PUBLISHED" if commit or pull_request else "PENDING"
    safe_objective = _safe(objective.replace("\n", " "))
    safe_stage = _safe(STAGE_LABELS[current_stage])
    safe_branch = _safe(branch or "not recorded yet", strip_backticks=True)
    return [
        '<table role="presentation">',
        "<tr>",
        '<td colspan="3" align="center">',
        "<h2>👁️ Amosclaud Live Execution · 3D Result Card</h2>",
        f"<strong>{safe_objective}</strong><br>",
        "<sub>REAL WORKFLOW EVIDENCE · GUARDED REPOSITORY EXECUTION</sub>",
        "</td>",
        "</tr>",
        "<tr>",
        '<td align="center"><strong>STATUS</strong><br>',
        f"<kbd>{_result_label(outcome)}</kbd></td>",
        '<td align="center"><strong>ACTIVE STAGE</strong><br>',
        f"<kbd>{safe_stage}</kbd></td>",
        '<td align="center"><strong>PROGRESS</strong><br>',
        f"<kbd>{progress}%</kbd></td>",
        "</tr>",
        "<tr>",
        '<td colspan="3">',
        "<strong>Execution rail</strong><br>",
        _stage_badges(current_stage, outcome),
        "</td>",
        "</tr>",
        "<tr>",
        '<td colspan="3">',
        f"<strong>Progress</strong><br><code>{_progress_bar(progress)} {progress}%</code>",
        "</td>",
        "</tr>",
        "<tr>",
        '<td align="center"><strong>TESTS</strong><br>',
        f"<code>{_safe(_test_summary(tests))}</code></td>",
        '<td align="center"><strong>FILES</strong><br>',
        f"<code>{len(files)} changed</code></td>",
        '<td align="center"><strong>DELIVERY</strong><br>',
        f"<code>{delivery}</code></td>",
        "</tr>",
        "<tr>",
        '<td colspan="3">',
        f"<strong>Branch</strong> · <code>{safe_branch}</code>",
        "</td>",
        "</tr>",
        "</table>",
        "<sub>▰▰▰ Amosclaud evidence layer · the raised card is backed by the expandable workflow record below.</sub>",
    ]


def render_dashboard(
    *,
    objective: str,
    current_stage: str,
    outcome: str = "running",
    files: list[str] | None = None,
    tests: list[TestCard] | None = None,
    commit: str = "",
    pull_request: str = "",
    branch: str = "",
) -> str:
    if current_stage not in STAGES:
        raise ValueError(f"unknown dashboard stage: {current_stage}")
    if outcome not in {"running", "passed", "failed"}:
        raise ValueError(f"unknown dashboard outcome: {outcome}")

    files = files or []
    tests = tests or []
    progress = _progress(current_stage, outcome)
    safe_objective = _safe(objective.replace("\n", " "))
    safe_branch = _safe(branch or "not recorded yet", strip_backticks=True)
    safe_commit = _safe(commit or "not created yet", strip_backticks=True)
    safe_pull_request = _safe(pull_request or "not opened yet", strip_backticks=True)

    lines = [DASHBOARD_MARKER]
    lines.extend(
        _render_3d_card(
            objective=objective,
            current_stage=current_stage,
            outcome=outcome,
            progress=progress,
            files=files,
            tests=tests,
            commit=commit,
            pull_request=pull_request,
            branch=branch,
        )
    )
    lines.extend(
        [
            "",
            "<details open>",
            "<summary><strong>Open exact execution evidence</strong></summary>",
            "",
            f"> **Objective:** {safe_objective}",
            "",
            f"**Progress:** `{progress}%`  |  **Stage:** `{STAGE_LABELS[current_stage]}`",
            "",
            "```text",
            "[" + "█" * (progress // 10) + "░" * (10 - progress // 10) + f"] {progress}%",
            "```",
            "",
            "## Execution path",
            "",
            "| Stage | State |",
            "|---|---|",
        ]
    )
    for stage in STAGES:
        status = _stage_status(stage, current_stage, outcome)
        lines.append(
            f"| {_icon(status)} | **{STAGE_LABELS[stage]}** — {status.upper()} |"
        )

    lines.extend(["", "## 🧪 Test cards", ""])
    if tests:
        lines.extend(["| Check | Result | Evidence |", "|---|---|---|"])
        for card in tests:
            name = _safe(card.name).replace("|", "\\|")
            detail = _safe(card.detail).replace("|", "\\|") or "Recorded by the workflow"
            lines.append(
                f"| {_icon(card.status)} **{name}** | `{card.status.upper()}` | {detail} |"
            )
    else:
        lines.append("⬜ Tests have not started yet.")

    lines.extend(["", "## 📁 Repository impact", ""])
    if files:
        for path in files[:12]:
            lines.append(f"- `{_safe(path, strip_backticks=True)}`")
        if len(files) > 12:
            lines.append(f"- …and {len(files) - 12} more files")
    else:
        lines.append("No changed files recorded yet.")

    lines.extend(
        [
            "",
            "## 📦 Delivery",
            "",
            f"- **Branch:** `{safe_branch}`",
            f"- **Commit:** `{safe_commit}`",
            f"- **Pull request:** {safe_pull_request}",
            "",
            "<sub>Every state shown above is generated from the active GitHub Actions run. Amosclaud never reports PASS before the corresponding command succeeds.</sub>",
            "",
            "</details>",
        ]
    )
    return "\n".join(lines)[:10_000]


def _latest_dashboard_comment(comments: list[dict[str, Any]]) -> int | None:
    for comment in reversed(comments):
        if DASHBOARD_MARKER in str(comment.get("body") or ""):
            comment_id = comment.get("id")
            if isinstance(comment_id, int):
                return comment_id
    return None


def publish_dashboard(bot: AmosclaudBot, issue_number: int, body: str) -> None:
    comments = bot._request(
        "GET", f"/repos/{bot.repository}/issues/{issue_number}/comments?per_page=100"
    )
    comment_id = _latest_dashboard_comment(
        comments if isinstance(comments, list) else []
    )
    if comment_id is None:
        bot.post_comment(issue_number, body)
        return
    bot._request(
        "PATCH",
        f"/repos/{bot.repository}/issues/comments/{comment_id}",
        {"body": body},
    )


def append_step_summary(body: str) -> None:
    summary = os.getenv("GITHUB_STEP_SUMMARY", "").strip()
    if not summary:
        return
    with Path(summary).open("a", encoding="utf-8") as handle:
        handle.write(body + "\n")


def _load_lines(path: str) -> list[str]:
    if not path or not Path(path).exists():
        return []
    return [
        line.strip()
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Publish the Amosclaud live execution dashboard"
    )
    parser.add_argument("--stage", choices=STAGES, required=True)
    parser.add_argument(
        "--outcome", choices=("running", "passed", "failed"), default="running"
    )
    parser.add_argument("--objective", default="Repository engineering task")
    parser.add_argument("--files", default="")
    parser.add_argument("--tests-json", default="")
    parser.add_argument("--commit", default="")
    parser.add_argument("--pull-request", default="")
    parser.add_argument("--branch", default="")
    args = parser.parse_args()

    tests: list[TestCard] = []
    if args.tests_json and Path(args.tests_json).exists():
        raw = json.loads(Path(args.tests_json).read_text(encoding="utf-8"))
        tests = [
            TestCard(
                str(item["name"]),
                str(item["status"]),
                str(item.get("detail", "")),
            )
            for item in raw
        ]

    body = render_dashboard(
        objective=args.objective,
        current_stage=args.stage,
        outcome=args.outcome,
        files=_load_lines(args.files),
        tests=tests,
        commit=args.commit,
        pull_request=args.pull_request,
        branch=args.branch,
    )
    append_step_summary(body)

    repository = os.getenv("GITHUB_REPOSITORY", "")
    issue_number = os.getenv("ISSUE_NUMBER", "")
    if repository and issue_number.isdigit():
        token = (
            os.getenv("AMOSCLAUD_GITHUB_TOKEN", "").strip()
            or os.getenv("GH_TOKEN", "").strip()
            or os.getenv("GITHUB_TOKEN", "").strip()
        )
        bot = AmosclaudBot(repository, token=token)
        publish_dashboard(bot, int(issue_number), body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

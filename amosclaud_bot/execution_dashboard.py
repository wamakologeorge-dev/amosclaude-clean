from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
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


@dataclass(frozen=True)
class TestCard:
    name: str
    status: str
    detail: str = ""


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

    files = files or []
    tests = tests or []
    completed = sum(
        1 for stage in STAGES if _stage_status(stage, current_stage, outcome) == "passed"
    )
    progress = round((completed / len(STAGES)) * 100)
    if outcome == "running":
        progress = max(progress, round((STAGES.index(current_stage) + 0.5) / len(STAGES) * 100))

    lines = [
        DASHBOARD_MARKER,
        "# 👁️ Amosclaud Live Execution",
        "",
        f"> **Objective:** {objective}",
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
    for stage in STAGES:
        status = _stage_status(stage, current_stage, outcome)
        lines.append(f"| {_icon(status)} | **{STAGE_LABELS[stage]}** — {status.upper()} |")

    lines.extend(["", "## 🧪 Test cards", ""])
    if tests:
        lines.extend(["| Check | Result | Evidence |", "|---|---|---|"])
        for card in tests:
            detail = card.detail.replace("|", "\\|") or "Recorded by the workflow"
            lines.append(f"| {_icon(card.status)} **{card.name}** | `{card.status.upper()}` | {detail} |")
    else:
        lines.append("⬜ Tests have not started yet.")

    lines.extend(["", "## 📁 Repository impact", ""])
    if files:
        for path in files[:12]:
            lines.append(f"- `{path}`")
        if len(files) > 12:
            lines.append(f"- …and {len(files) - 12} more files")
    else:
        lines.append("No changed files recorded yet.")

    lines.extend(
        [
            "",
            "## 📦 Delivery",
            "",
            f"- **Branch:** `{branch or 'not recorded yet'}`",
            f"- **Commit:** `{commit or 'not created yet'}`",
            f"- **Pull request:** {pull_request or 'not opened yet'}",
            "",
            "<sub>Every state shown above is generated from the active GitHub Actions run. Amosclaud never reports PASS before the corresponding command succeeds.</sub>",
        ]
    )
    return "\n".join(lines)[:6000]


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
    comment_id = _latest_dashboard_comment(comments if isinstance(comments, list) else [])
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
    return [line.strip() for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish the Amosclaud live execution dashboard")
    parser.add_argument("--stage", choices=STAGES, required=True)
    parser.add_argument("--outcome", choices=("running", "passed", "failed"), default="running")
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
        tests = [TestCard(str(item["name"]), str(item["status"]), str(item.get("detail", ""))) for item in raw]

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
        bot = AmosclaudBot(repository, token=os.getenv("GITHUB_TOKEN", ""))
        publish_dashboard(bot, int(issue_number), body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import json
import re
from typing import Any

from .bot import AmosclaudBot, WRITE_ASSOCIATIONS, parse_command

PLAN_MARKER = "amosclaud-autonomous-plan"
CONTINUE_PHRASES = {
    "continue",
    "resume",
    "continue the task",
    "resume the task",
    "finish the remaining work",
    "finish remaining work",
    "complete the remaining work",
}


def _normalized_request(text: str) -> str:
    normalized = " ".join((text or "").strip().split()).lower()
    for name in ("@amosclaud-bot", "@amosclaud"):
        if normalized.startswith(name):
            return normalized[len(name) :].strip().rstrip(".")
    return normalized.rstrip(".")


def is_continue_request(text: str) -> bool:
    return _normalized_request(text) in CONTINUE_PHRASES


def plan_steps(command: str) -> tuple[str, ...]:
    if command == "fix":
        return (
            "Analyze the repository and the requested objective",
            "Design the smallest safe implementation",
            "Create or modify the required files",
            "Add or update regression tests",
            "Run compilation and targeted tests",
            "Commit verified changes and open a pull request",
        )
    if command == "verify":
        return (
            "Identify the relevant verification scope",
            "Run repository checks and targeted tests",
            "Collect factual evidence",
            "Report the verified result",
        )
    if command == "review":
        return (
            "Inspect the proposed changes",
            "Identify correctness, security, and regression risks",
            "Check available verification evidence",
            "Report actionable findings",
        )
    return (
        "Inspect the repository",
        "Understand the objective and constraints",
        "Identify the files and checks involved",
        "Report a recommended implementation path",
    )


def encode_plan_marker(command: str, objective: str) -> str:
    payload = json.dumps(
        {"version": 1, "command": command, "objective": objective},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f"<!-- {PLAN_MARKER}:{payload} -->"


def decode_plan_marker(body: str) -> dict[str, str] | None:
    match = re.search(rf"<!--\s*{re.escape(PLAN_MARKER)}:(\{{.*?\}})\s*-->", body or "", re.DOTALL)
    if not match:
        return None
    try:
        payload = json.loads(match.group(1))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    command = str(payload.get("command") or "").strip()
    objective = " ".join(str(payload.get("objective") or "").strip().split())
    if command not in {"fix", "inspect", "review", "verify"} or not objective:
        return None
    return {"command": command, "objective": objective}


def latest_plan(comments: list[dict[str, Any]]) -> dict[str, str] | None:
    for comment in reversed(comments):
        plan = decode_plan_marker(str(comment.get("body") or ""))
        if plan:
            return plan
    return None


def format_plan(command: str, objective: str, *, resumed: bool = False) -> str:
    heading = "### Amosclaud — Autonomous Plan Resumed" if resumed else "### Amosclaud — Autonomous Plan"
    steps = plan_steps(command)
    rendered = []
    for index, step in enumerate(steps):
        icon = "🟩" if index < 2 else "⬜"
        rendered.append(f"{icon} {step}")
    return (
        f"{heading}\n\n"
        f"**Objective:** {objective}\n\n"
        + "\n".join(rendered)
        + "\n\nProceeding through the existing approval, privacy, verification, commit, and pull-request gates.\n"
        + encode_plan_marker(command, objective)
    )


def resolve_continuation(bot: AmosclaudBot, payload: dict[str, Any]) -> bool:
    comment = payload.get("comment") or {}
    if not is_continue_request(str(comment.get("body") or "")):
        return False

    issue = payload.get("issue") or {}
    number = int(issue.get("number"))
    comments = bot._request("GET", f"/repos/{bot.repository}/issues/{number}/comments?per_page=100")
    plan = latest_plan(comments if isinstance(comments, list) else [])
    if not plan:
        bot.post_comment(
            number,
            "### Amosclaud — Nothing to resume\nNo earlier autonomous plan was found in this issue. Start a task with `@amosclaud <objective>`."
        )
        return True

    comment["body"] = f"@amosclaud {plan['command']} {plan['objective']}"
    payload["comment"] = comment
    payload["_amosclaud_resumed_plan"] = plan
    return False


def announce_plan(bot: AmosclaudBot, payload: dict[str, Any]) -> None:
    comment = payload.get("comment") or {}
    association = str(comment.get("author_association") or "NONE").upper()
    command, objective = parse_command(str(comment.get("body") or ""))
    if command not in {"fix", "inspect", "review", "verify"} or not objective:
        return
    if command == "fix" and association not in WRITE_ASSOCIATIONS:
        return

    issue = payload.get("issue") or {}
    number = int(issue.get("number"))
    resumed = bool(payload.get("_amosclaud_resumed_plan"))
    bot.post_comment(number, format_plan(command, objective, resumed=resumed))

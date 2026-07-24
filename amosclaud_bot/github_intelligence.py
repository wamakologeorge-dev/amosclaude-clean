from __future__ import annotations

import json
import re
from typing import Any

from .autonomous_brain import GitHubAutonomousBrain
from .bot import AmosclaudBot, parse_command
from .status_board import build_status_board

GOAL_MARKER = "amosclaud-autonomous-goal"
GOAL_STAGES = (
    "Understand and triage the objective",
    "Inspect current repository evidence",
    "Build a multi-task implementation plan",
    "Execute only authorized tasks",
    "Verify each completed task independently",
    "Publish progress and verified outcomes",
)


def _terms(value: str) -> set[str]:
    return {
        term.lower()
        for term in re.findall(r"[A-Za-z0-9_]{3,}", value or "")
        if term.lower() not in {"this", "that", "with", "from", "have", "issue", "please"}
    }


def classify_issue(issue: dict[str, Any]) -> dict[str, Any]:
    """Return deterministic GitHub triage guidance without changing the issue."""
    title = str(issue.get("title") or "")
    body = str(issue.get("body") or "")
    text = f"{title}\n{body}".lower()

    security = any(word in text for word in ("security", "vulnerability", "secret", "token", "credential", "auth"))
    ci = any(word in text for word in ("ci", "workflow", "action", "build", "test fail", "pipeline"))
    bug = any(word in text for word in ("bug", "broken", "error", "fail", "crash", "regression"))
    feature = any(word in text for word in ("feature", "add ", "implement", "support", "improve", "create"))
    docs = any(word in text for word in ("readme", "documentation", "docs", "guide"))

    labels: list[str] = []
    if security:
        labels.append("security")
    if ci:
        labels.append("ci")
    if bug:
        labels.append("bug")
    if feature:
        labels.append("enhancement")
    if docs:
        labels.append("documentation")
    if not labels:
        labels.append("needs-triage")

    if security:
        priority, risk = "P0", "high"
    elif ci and bug:
        priority, risk = "P1", "high"
    elif bug:
        priority, risk = "P2", "medium"
    else:
        priority, risk = "P3", "low"

    agent_roles = ["Receive and understand", "Perceive repository evidence", "Plan with model"]
    if bug or feature:
        agent_roles.append("Act when authorized")
    agent_roles.append("Verify and report")

    return {
        "priority": priority,
        "risk": risk,
        "suggested_labels": labels,
        "agent_roles": agent_roles,
        "search_terms": sorted(_terms(f"{title} {body}"))[:12],
        "write_requires_authorization": bool(bug or feature),
        "private_review_recommended": security,
    }


def render_triage(issue: dict[str, Any]) -> str:
    triage = classify_issue(issue)
    labels = ", ".join(f"`{label}`" for label in triage["suggested_labels"])
    roles = " → ".join(triage["agent_roles"])
    terms = ", ".join(f"`{term}`" for term in triage["search_terms"]) or "none"
    private = "Yes" if triage["private_review_recommended"] else "No"
    return (
        "### Amosclaud — Autonomous Issue Triage\n\n"
        f"- **Priority:** `{triage['priority']}`\n"
        f"- **Risk:** `{triage['risk'].upper()}`\n"
        f"- **Suggested labels:** {labels}\n"
        f"- **Assigned autonomous roles:** {roles}\n"
        f"- **Duplicate-search terms:** {terms}\n"
        f"- **Private review recommended:** {private}\n"
        f"- **Write authorization required:** {'Yes' if triage['write_requires_authorization'] else 'No'}\n\n"
        "This is evidence-based guidance only. Labels, human assignees, repository writes, and publication remain governed by GitHub permissions and Amosclaud approval gates."
    )[:5000]


def encode_goal_marker(objective: str, completed: int = 0) -> str:
    payload = json.dumps(
        {"version": 1, "objective": " ".join(objective.split()), "completed": max(0, min(completed, len(GOAL_STAGES)))},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f"<!-- {GOAL_MARKER}:{payload} -->"


def decode_goal_marker(body: str) -> dict[str, Any] | None:
    match = re.search(rf"<!--\s*{re.escape(GOAL_MARKER)}:(\{{.*?\}})\s*-->", body or "", re.DOTALL)
    if not match:
        return None
    try:
        payload = json.loads(match.group(1))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    objective = " ".join(str(payload.get("objective") or "").split())
    if not objective:
        return None
    try:
        completed = int(payload.get("completed") or 0)
    except (TypeError, ValueError):
        completed = 0
    return {"objective": objective, "completed": max(0, min(completed, len(GOAL_STAGES)))}


def latest_goal(comments: list[dict[str, Any]]) -> dict[str, Any] | None:
    for comment in reversed(comments):
        goal = decode_goal_marker(str(comment.get("body") or ""))
        if goal:
            return goal
    return None


def render_goal(objective: str, *, completed: int = 0, brain: dict[str, Any] | None = None) -> str:
    completed = max(0, min(completed, len(GOAL_STAGES)))
    progress = round((completed / len(GOAL_STAGES)) * 100)
    lines = [
        "### Amosclaud — Goal-Driven Mission",
        "",
        f"**Objective:** {objective}",
        f"**Progress:** `{progress}%`",
        "",
        "## Mission tasks",
    ]
    for index, stage in enumerate(GOAL_STAGES):
        lines.append(f"{'🟩' if index < completed else '⬜'} {stage}")
    if brain:
        roll = brain.get("rollimage", {})
        lines.extend(
            [
                "",
                "## Brain coordination",
                f"- **RollImage:** `{roll.get('image_id', 'not-created')}`",
                f"- **Active roles:** {len(brain.get('agent_roles', []))}",
                f"- **Proven memories:** {len(brain.get('proven_memories', []))}",
                f"- **Approved lessons:** {len(brain.get('approved_lessons', []))}",
            ]
        )
    lines.extend(
        [
            "",
            "Use `@amosclaud continue` to resume the current issue plan. Mission progress must be advanced only by repository evidence, completed checks, or verified delivery.",
            encode_goal_marker(objective, completed),
        ]
    )
    return "\n".join(lines)[:6000]


def render_health(bot: AmosclaudBot, payload: dict[str, Any]) -> str:
    board = build_status_board(bot, payload)
    brain = GitHubAutonomousBrain(bot.workspace, bot.repository)
    stats = brain.memory.stats()
    return (
        board
        + "\n\n## Autonomous brain health\n"
        + f"- **Stored outcomes:** {stats.get('memories', 0)}\n"
        + f"- **Verified successful lessons:** {stats.get('successful_lessons', 0)}\n"
        + f"- **Recorded failed approaches:** {stats.get('failed_lessons', 0)}\n"
        + f"- **Average confidence:** {float(stats.get('average_confidence', 0)):.2f}\n"
        + "- **Website dependency:** none\n"
        + "- **Railway acceptance dependency:** none"
    )[:5000]


def handle_intelligence_request(bot: AmosclaudBot, payload: dict[str, Any]) -> int | None:
    comment = payload.get("comment") or {}
    command, objective = parse_command(str(comment.get("body") or ""))
    if command not in {"triage", "health", "goal"}:
        return None
    issue = payload.get("issue") or {}
    number = issue.get("number")
    if not isinstance(number, int):
        return 0

    if command == "triage":
        bot.post_comment(number, render_triage(issue))
        return 0
    if command == "health":
        bot.post_comment(number, render_health(bot, payload))
        return 0

    if objective:
        brain = GitHubAutonomousBrain(bot.workspace, bot.repository).prepare("inspect", objective)
        bot.post_comment(number, render_goal(objective, brain=brain))
        return 0

    comments = bot._request("GET", f"/repos/{bot.repository}/issues/{number}/comments?per_page=100")
    goal = latest_goal(comments if isinstance(comments, list) else [])
    if not goal:
        bot.post_comment(number, "### Amosclaud — No active goal\nStart one with `@amosclaud goal <objective>`. ")
        return 0
    brain = GitHubAutonomousBrain(bot.workspace, bot.repository).prepare("inspect", goal["objective"])
    bot.post_comment(number, render_goal(goal["objective"], completed=goal["completed"], brain=brain))
    return 0

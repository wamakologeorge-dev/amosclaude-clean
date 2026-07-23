from __future__ import annotations

from typing import Any

from .autonomous_brain import GitHubAutonomousBrain
from .bot import AmosclaudBot
from .github_intelligence import latest_goal, render_goal, render_health, render_triage

BOT_NAMES = ("@amosclaud-bot", "@amosclaud")


def parse_intelligence_command(text: str) -> tuple[str | None, str]:
    normalized = " ".join((text or "").strip().split())
    lowered = normalized.lower()
    matched = next((name for name in BOT_NAMES if lowered.startswith(name)), None)
    if not matched:
        return None, ""
    remainder = normalized[len(matched) :].strip()
    command, _, objective = remainder.partition(" ")
    command = command.lower().strip()
    if command not in {"triage", "health", "goal"}:
        return None, ""
    return command, objective.strip()


def handle_intelligence_request(bot: AmosclaudBot, payload: dict[str, Any]) -> int | None:
    comment = payload.get("comment") or {}
    command, objective = parse_intelligence_command(str(comment.get("body") or ""))
    if not command:
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
        context = GitHubAutonomousBrain(bot.workspace, bot.repository).prepare("goal", objective)
        bot.post_comment(number, render_goal(objective, brain=context))
        return 0

    comments = bot._request("GET", f"/repos/{bot.repository}/issues/{number}/comments?per_page=100")
    goal = latest_goal(comments if isinstance(comments, list) else [])
    if not goal:
        bot.post_comment(number, "### Amosclaud — No active goal\nStart one with `@amosclaud goal <objective>`. ")
        return 0
    context = GitHubAutonomousBrain(bot.workspace, bot.repository).prepare("goal", goal["objective"])
    bot.post_comment(number, render_goal(goal["objective"], completed=goal["completed"], brain=context))
    return 0

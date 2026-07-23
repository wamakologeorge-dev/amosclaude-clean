from __future__ import annotations

from typing import Any

from .bot import AmosclaudBot
from .github_intelligence import render_health, render_triage
from .mission_ledger import handle_mission_request

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
    if command not in {"triage", "health", "goal", "mission"}:
        return None, ""
    return command, objective.strip()


def handle_intelligence_request(bot: AmosclaudBot, payload: dict[str, Any]) -> int | None:
    comment = payload.get("comment") or {}
    command, _objective = parse_intelligence_command(str(comment.get("body") or ""))
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
    return handle_mission_request(bot, payload)

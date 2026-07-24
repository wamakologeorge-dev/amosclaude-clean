"""GitHub-native Amosclaud Bot integration."""

import os
from typing import Any

from .autonomous_brain import GitHubAutonomousBrain
from .bot import AmosclaudBot, BotResponse, parse_command

_ORIGINAL_RUN_LOCAL = AmosclaudBot._run_local


def _brain_aware_run_local(
    self: AmosclaudBot,
    command: str,
    objective: str,
    *,
    allow_writes: bool,
) -> dict[str, Any]:
    brain = GitHubAutonomousBrain(self.workspace, self.repository)
    context = brain.prepare(command, objective)
    result = _ORIGINAL_RUN_LOCAL(self, command, objective, allow_writes=allow_writes)
    if not isinstance(result, dict):
        result = {"status": "unknown", "message": str(result)}
    else:
        result = dict(result)
    result["autonomous_brain"] = context
    memory = brain.observe(
        command,
        objective,
        result,
        source_run_id=os.getenv("GITHUB_RUN_ID", ""),
    )
    evidence = [str(item) for item in (result.get("evidence") or [])]
    evidence.append(
        "Autonomous brain: "
        f"level {context['current_level']}, "
        f"{len(context['proven_memories'])} proven memories, "
        f"{len(context['failed_attempts_to_avoid'])} failed attempts, "
        f"{len(context['approved_lessons'])} approved lessons; "
        f"outcome recorded as {memory['outcome']}."
    )
    result["evidence"] = evidence
    return result


AmosclaudBot._run_local = _brain_aware_run_local

__all__ = [
    "AmosclaudBot",
    "BotResponse",
    "GitHubAutonomousBrain",
    "parse_command",
]

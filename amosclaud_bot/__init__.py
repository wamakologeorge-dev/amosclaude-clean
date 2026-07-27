"""GitHub-native Amosclaud Bot integration."""

import os
from typing import Any, Mapping

from . import bot as bot_module
from .autonomous_brain import GitHubAutonomousBrain
from .bot import AmosclaudBot, BotResponse, parse_command

_ORIGINAL_RUN_LOCAL = AmosclaudBot._run_local
_ORIGINAL_HANDLE_COMMENT = AmosclaudBot.handle_comment


def _legacy_kernel_call(
    self: AmosclaudBot,
    command: str,
    objective: str,
    *,
    allow_writes: bool,
) -> dict[str, Any]:
    """Support simple test/extension kernels that predate signed-grant kwargs."""

    kernel = bot_module.get_autonomous_kernel(self.workspace)
    if command == "fix":
        if not allow_writes:
            return {
                "status": "blocked",
                "error": "write_not_authorized",
                "evidence": [
                    "Amosclaud-Fixer is available, but repository writes are "
                    "limited to trusted repository collaborators."
                ],
            }
        return kernel.repair(issue=objective, authorized_writes=True)
    mode = {"inspect": "plan", "review": "review", "verify": "verify"}.get(
        command,
        "plan",
    )
    return kernel.execute(
        objective=objective,
        mode=mode,
        authorized_writes=False,
        metadata={
            "source": "amosclaud-bot",
            "repository": self.repository,
            "github_run_id": os.getenv("GITHUB_RUN_ID", ""),
        },
    )


def _brain_aware_run_local(
    self: AmosclaudBot,
    command: str,
    objective: str,
    *,
    allow_writes: bool,
    security_source: Mapping[str, Any] | None = None,
    approval: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    brain = GitHubAutonomousBrain(self.workspace, self.repository)
    context = brain.prepare(command, objective)
    try:
        result = _ORIGINAL_RUN_LOCAL(
            self,
            command,
            objective,
            allow_writes=allow_writes,
            security_source=security_source,
            approval=approval,
        )
    except TypeError as exc:
        if "unexpected keyword argument" not in str(exc):
            raise
        result = _legacy_kernel_call(
            self,
            command,
            objective,
            allow_writes=allow_writes,
        )
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


def _status_aware_handle_comment(
    self: AmosclaudBot,
    payload: dict[str, Any],
) -> BotResponse:
    response = _ORIGINAL_HANDLE_COMMENT(self, payload)
    command, _ = parse_command(str((payload.get("comment") or {}).get("body") or ""))
    marker = "Natural-language assistant mode: **enabled**"
    if command == "status" and marker not in response.body:
        body = response.body.replace(
            "- Direct default-branch writes: **prohibited**",
            f"- {marker}\n- Direct default-branch writes: **prohibited**",
        )
        return BotResponse(body=body, should_comment=response.should_comment)
    return response


AmosclaudBot._run_local = _brain_aware_run_local
AmosclaudBot.handle_comment = _status_aware_handle_comment

__all__ = [
    "AmosclaudBot",
    "BotResponse",
    "GitHubAutonomousBrain",
    "parse_command",
]

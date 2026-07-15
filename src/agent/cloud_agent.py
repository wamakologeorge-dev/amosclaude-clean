"""Conversational Cloud Agent backed by the one Amosclaud Autonomous brain."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .model import AutonomousModelGateway
from .rollimage import RollImageEngine


@dataclass
class CloudAgentReply:
    reply: str
    status: str
    rollimage: dict[str, Any]
    instruction_detected: bool
    requires_authorization: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AmosclaudCloudAgent:
    """Replies to messages and routes actionable instructions to Autonomous."""

    ACTION_WORDS = {"build", "create", "fix", "change", "delete", "deploy", "commit", "merge", "run", "test"}
    WRITE_WORDS = {"build", "create", "fix", "change", "delete", "deploy", "commit", "merge"}

    def __init__(self) -> None:
        self.model = AutonomousModelGateway()
        self.rollimage = RollImageEngine()

    def reply(self, message: str, *, evidence: list[str] | None = None) -> CloudAgentReply:
        image = self.rollimage.create(message, evidence)
        words = {word.strip(".,!?():;").lower() for word in message.split()}
        actionable = bool(words & self.ACTION_WORDS)
        requires_authorization = bool(words & self.WRITE_WORDS)

        if self.model.available():
            answer = self.model.complete(
                message,
                [self.rollimage.system_context(image), *(evidence or [])],
            )
        elif actionable:
            answer = (
                "I understand the instruction. I can inspect and plan now. "
                + ("Applying changes requires explicit authorization. " if requires_authorization else "")
                + "The cloud model connection is not ready, so I will not pretend the action completed."
            )
        else:
            answer = "Amosclaud Cloud Agent is online. Tell me the outcome you want, and I will understand, inspect, plan, verify, and report."

        return CloudAgentReply(
            reply=answer,
            status="ready" if self.model.available() else "degraded",
            rollimage=image.to_dict(),
            instruction_detected=actionable,
            requires_authorization=requires_authorization,
        )


def chat_with_autonomous(message: str, evidence: list[str] | None = None) -> dict[str, Any]:
    return AmosclaudCloudAgent().reply(message, evidence=evidence).to_dict()

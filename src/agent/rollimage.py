"""RollImage working context for the Amosclaud Autonomous brain."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any


@dataclass(frozen=True)
class BrainRollImage:
    image_id: str
    created_at: str
    intent: str
    known_facts: list[str]
    unknowns: list[str]
    next_actions: list[str]
    safety_rules: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RollImageEngine:
    """Creates a fresh evidence-grounded reasoning snapshot for each request."""

    def create(self, message: str, evidence: list[str] | None = None) -> BrainRollImage:
        intent = " ".join(message.strip().split()) or "Ask for a clear objective"
        facts = [str(item)[:500] for item in (evidence or []) if str(item).strip()][:20]
        digest = sha256((intent + "\n" + "\n".join(facts)).encode()).hexdigest()[:20]
        return BrainRollImage(
            image_id=f"roll-{digest}",
            created_at=datetime.now(timezone.utc).isoformat(),
            intent=intent,
            known_facts=facts,
            unknowns=[] if facts else ["Evidence has not been inspected yet"],
            next_actions=["Understand", "Inspect", "Plan", "Act when authorized", "Verify", "Report"],
            safety_rules=[
                "Use verified evidence",
                "Stay inside the selected workspace",
                "Require authorization before changes",
                "Keep private configuration private",
                "Report blockers truthfully",
            ],
        )

    def system_context(self, image: BrainRollImage) -> str:
        return (
            f"RollImage {image.image_id}\n"
            f"Intent: {image.intent}\n"
            f"Facts: {'; '.join(image.known_facts) or 'none'}\n"
            f"Unknowns: {'; '.join(image.unknowns) or 'none'}\n"
            f"Cycle: {' -> '.join(image.next_actions)}\n"
            f"Rules: {'; '.join(image.safety_rules)}"
        )

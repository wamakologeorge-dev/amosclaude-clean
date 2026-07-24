"""Central operator contract for Amosclaud-bot.

The platform, GitHub App, CLI, and internal workers should translate user intent
through this module before creating a global task. This keeps one public operator
while specialized agents remain implementation details.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

OperatorMode = Literal["ask", "build", "fix", "test", "review", "deploy", "monitor"]


@dataclass(frozen=True, slots=True)
class OperatorRequest:
    """A normalized request accepted by the Amosclaud-bot operator."""

    objective: str
    repository: str | None = None
    mode: OperatorMode | None = None
    require_approval: bool = True
    source: str = "amosclaud-platform"
    conversation_id: str | None = None
    metadata: dict[str, Any] | None = None


_MODE_TERMS: tuple[tuple[OperatorMode, tuple[str, ...]], ...] = (
    ("deploy", ("deploy", "release", "publish", "ship")),
    ("fix", ("fix", "repair", "debug", "broken", "error", "failing")),
    ("test", ("test", "verify", "check ci", "run checks")),
    ("review", ("review", "inspect", "audit", "pull request", " pr ")),
    ("monitor", ("monitor", "watch", "alert", "status")),
    ("build", ("build", "create", "implement", "add", "make")),
)


def infer_mode(objective: str) -> OperatorMode:
    """Infer the first safe execution mode from a natural-language objective."""

    normalized = f" {objective.strip().lower()} "
    for mode, terms in _MODE_TERMS:
        if any(term in normalized for term in terms):
            return mode
    return "ask"


def normalize_operator_request(request: OperatorRequest) -> dict[str, Any]:
    """Convert an operator request into the shared global-task payload.

    The returned shape matches ``task_router.TaskCreate`` without importing the
    API layer, so web, GitHub App, CLI, and worker packages can share it safely.
    """

    objective = request.objective.strip()
    if len(objective) < 3:
        raise ValueError("objective must contain at least 3 characters")

    mode = request.mode or infer_mode(objective)
    metadata = dict(request.metadata or {})
    metadata.update(
        {
            "operator": "Amosclaud-bot",
            "source": request.source,
            "conversation_id": request.conversation_id,
            "single_brain": True,
        }
    )

    return {
        "objective": objective,
        "repository": request.repository,
        "mode": mode,
        "delivery": "report" if mode in {"ask", "monitor"} else "pull_request",
        "execution_target": "github" if request.repository else "cloud",
        "require_approval": request.require_approval,
        "metadata": metadata,
    }

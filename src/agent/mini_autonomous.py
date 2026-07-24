"""Mini Autonomous worker for diagnosis and repair preparation."""
from __future__ import annotations

from typing import Any

from .actions import run_autonomous
from .rollimage import RollImageEngine


class MiniAutonomous:
    """Prepares a smart repair task, then delegates to the one orchestrator."""

    def __init__(self) -> None:
        self.brain = RollImageEngine()

    def handle(self, issue: str, *, workspace: str = ".", authorized_writes: bool = False) -> dict[str, Any]:
        image = self.brain.create(issue)
        objective = (
            f"Mini Autonomous repair request: {issue}\n\n"
            f"Brain context:\n{self.brain.system_context(image)}"
        )
        result = run_autonomous(
            objective=objective,
            mode="fix" if authorized_writes else "plan",
            authorized_writes=authorized_writes,
            workspace=workspace,
        )
        result["rollimage"] = image.to_dict()
        result["worker"] = "mini-autonomous"
        return result


def run_mini_autonomous(issue: str, workspace: str = ".", authorized_writes: bool = False) -> dict[str, Any]:
    return MiniAutonomous().handle(issue, workspace=workspace, authorized_writes=authorized_writes)

"""Legacy CodexAgent facade backed by Amosclaud Autonomous."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from src.amosclaud_os.kernel import get_autonomous_kernel


class CodexAgent:
    def __init__(self, workspace_root: str | Path = ".") -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.kernel = get_autonomous_kernel(self.workspace_root)
        self.provider = "amosclaud"

    def get_workspace_map(self) -> str:
        return "\n".join(str(item) for item in self.kernel.status().get("capabilities") or [])

    def execute_local_command(self, command: str) -> tuple[int, str, str]:
        del command
        return 2, "", "Direct shell execution was removed. Submit a governed Autonomous task instead."

    def parse_and_execute_actions(self, response_text: str) -> list[dict[str, Any]]:
        if not response_text.strip():
            return []
        return [{
            "action": "legacy-action-rejected",
            "success": False,
            "error": "Model-authored actions require Amosclaud Autonomous authorization and verification.",
        }]

    def run_autonomous_loop(
        self,
        user_prompt: str,
        max_iterations: int = 5,
        *,
        mode: str = "plan",
        authorized_writes: bool = False,
    ) -> dict[str, Any]:
        return self.kernel.execute(
            objective=user_prompt,
            mode=mode,
            authorized_writes=authorized_writes,
            metadata={
                "compatibility_entrypoint": "amoscloud_ai.agent.CodexAgent",
                "requested_max_iterations": max(1, int(max_iterations)),
            },
        )


__all__ = ["CodexAgent"]

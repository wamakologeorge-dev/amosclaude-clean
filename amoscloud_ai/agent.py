"""Compatibility adapter for the canonical Amosclaud Autonomous kernel.

Historically this module implemented an independent Codex loop with direct shell
and filesystem access plus third-party provider keys.  That created a second
agent identity and bypassed the platform's authorization and verification
boundaries.  Existing imports may continue to use :class:`CodexAgent`, but all
work is now delegated to the single process-wide ``AutonomousKernel``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

from src.amosclaud_os.kernel import AutonomousKernel, get_autonomous_kernel


CODEX_SYSTEM_PROMPT = (
    "You are Amosclaud Autonomous. Use the governed repository, model, fixer, "
    "and verification capabilities of the single Amosclaud Autonomous kernel."
)


class CodexAgent:
    """Backward-compatible facade for Amosclaud Autonomous.

    The facade does not execute model-generated XML, arbitrary shell commands,
    or direct file writes.  Write-capable requests require explicit
    ``authorized_writes=True`` and are processed by the canonical kernel.
    """

    def __init__(self, workspace_root: str | Path = ".") -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.kernel: AutonomousKernel = get_autonomous_kernel(self.workspace_root)
        self.provider = "amosclaud"

    def get_workspace_map(self) -> str:
        """Return a bounded capability view rather than exposing every file."""
        status = self.kernel.status()
        capabilities = status.get("capabilities") or []
        return "\n".join(str(item) for item in capabilities)

    def execute_local_command(self, command: str) -> Tuple[int, str, str]:
        """Reject the removed direct-shell compatibility method."""
        return (
            2,
            "",
            "Direct shell execution was removed. Submit a governed Autonomous task instead.",
        )

    def parse_and_execute_actions(self, response_text: str) -> List[Dict[str, Any]]:
        """Do not execute legacy XML actions returned by a model."""
        return [
            {
                "action": "legacy-action-rejected",
                "success": False,
                "error": (
                    "Model-authored XML actions are not executable. Amosclaud Autonomous "
                    "must authorize, run, and verify each operation."
                ),
            }
        ] if response_text.strip() else []

    def run_turn(
        self,
        conversation_history: List[Dict[str, str]],
        *,
        authorized_writes: bool = False,
    ) -> Tuple[str, List[Dict[str, Any]]]:
        objective = "\n".join(
            str(message.get("content", ""))
            for message in conversation_history
            if message.get("role") == "user"
        ).strip()
        result = self.kernel.assist(
            message=objective or "Inspect the current Amosclaud workspace.",
            execute=authorized_writes,
            authorized_writes=authorized_writes,
        )
        return str(result.get("reply") or result.get("message") or result), [result]

    def run_autonomous_loop(
        self,
        user_prompt: str,
        max_iterations: int = 5,
        *,
        mode: str = "plan",
        authorized_writes: bool = False,
    ) -> Dict[str, Any]:
        """Run one governed mission; the kernel owns iteration and verification."""
        return self.kernel.execute(
            objective=user_prompt,
            mode=mode,
            authorized_writes=authorized_writes,
            metadata={
                "compatibility_entrypoint": "amoscloud_ai.agent.CodexAgent",
                "requested_max_iterations": max(1, int(max_iterations)),
            },
        )


__all__ = ["CODEX_SYSTEM_PROMPT", "CodexAgent"]

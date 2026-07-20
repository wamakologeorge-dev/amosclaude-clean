"""Legacy CodexAgent facade backed by Amosclaud Autonomous.

The compatibility API remains available for older callers, but commands and file
operations are submitted to the canonical kernel. Nothing executes through a
second agent loop or an ungoverned ``shell=True`` subprocess.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from src.amosclaud_os.kernel import get_autonomous_kernel


_WRITE_FILE_PATTERN = re.compile(
    r'<write_file\s+path=["\'](?P<path>[^"\']+)["\']\s*>(?P<content>.*?)</write_file>',
    re.DOTALL,
)
_EXECUTE_PATTERN = re.compile(r"<execute>(?P<command>.*?)</execute>", re.DOTALL)


class CodexAgent:
    """Backward-compatible interface to the single Amosclaud Autonomous kernel."""

    def __init__(self, workspace_root: str | Path = ".") -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.kernel = get_autonomous_kernel(self.workspace_root)
        self.provider = "amosclaud"

    def get_workspace_map(self) -> str:
        return "\n".join(
            str(item) for item in self.kernel.status().get("capabilities") or []
        )

    def execute_local_command(
        self,
        command: str,
        *,
        authorized_writes: bool = False,
    ) -> tuple[int, str, str]:
        """Submit a command objective to Autonomous instead of spawning a shell.

        The canonical orchestrator decides which approved tool may satisfy the
        request. Commands that could mutate the workspace require explicit write
        authorization and all outcomes remain subject to verification.
        """
        command = command.strip()
        if not command:
            return 2, "", "A command objective is required."

        result = self.kernel.execute(
            objective=f"Run this approved workspace command and report evidence: {command}",
            mode="test" if not authorized_writes else "build",
            authorized_writes=authorized_writes,
            metadata={
                "compatibility_entrypoint": "amoscloud_ai.agent.CodexAgent.execute_local_command",
                "requested_command": command,
                "direct_shell": False,
            },
        )
        status = str(result.get("status") or "").lower()
        blocked = status == "blocked" or result.get("error") == "write_not_authorized"
        failed = result.get("failed") is True or status in {"error", "failed"}
        output = str(result.get("summary") or result.get("reply") or result)
        error = str(result.get("error") or "")
        return (2 if blocked else 1 if failed else 0), output, error

    def parse_and_execute_actions(
        self,
        response_text: str,
        *,
        authorized_writes: bool = False,
    ) -> list[dict[str, Any]]:
        """Translate legacy action markup into governed kernel operations."""
        if not response_text.strip():
            return []

        results: list[dict[str, Any]] = []
        for match in _WRITE_FILE_PATTERN.finditer(response_text):
            path = match.group("path").strip()
            content = match.group("content")
            outcome = self.kernel.write_document(
                path,
                content,
                authorized_writes=authorized_writes,
            )
            results.append(
                {
                    "action": "write_file",
                    "path": path,
                    "success": str(outcome.get("status", "")).lower()
                    in {"completed", "passed", "success", "written"}
                    and not outcome.get("error"),
                    "result": outcome,
                }
            )

        for match in _EXECUTE_PATTERN.finditer(response_text):
            command = match.group("command").strip()
            code, stdout, stderr = self.execute_local_command(
                command,
                authorized_writes=authorized_writes,
            )
            results.append(
                {
                    "action": "execute",
                    "command": command,
                    "success": code == 0,
                    "exit_code": code,
                    "stdout": stdout,
                    "stderr": stderr,
                }
            )

        if not results:
            results.append(
                {
                    "action": "autonomous-task",
                    "success": True,
                    "result": self.kernel.execute(
                        objective=response_text,
                        mode="plan",
                        authorized_writes=False,
                        metadata={"legacy_action_markup": True},
                    ),
                }
            )
        return results

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

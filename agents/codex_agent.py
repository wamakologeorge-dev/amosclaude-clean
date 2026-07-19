"""Restricted Amosclaud-native software engineering worker.

The worker performs a bounded model/action loop inside one resolved workspace.
It never pushes or merges code. Platform state is reported through the signed
PlatformByteBus and success requires an approved verification command.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import uuid
from pathlib import Path
from typing import Any


_ALLOWED_COMMAND_PREFIXES: tuple[tuple[str, ...], ...] = (
    ("python", "-m", "compileall"),
    ("python3", "-m", "compileall"),
    ("python", "-m", "pytest"),
    ("python3", "-m", "pytest"),
    ("pytest",),
    ("flake8",),
    ("ruff", "check"),
)
_PROTECTED_PARTS = {".git", ".github", ".env", "secrets", "credentials"}
_MAX_WRITE_BYTES = 512_000
_MAX_OUTPUT_CHARS = 40_000


class AgentPolicyError(RuntimeError):
    """Raised when a requested action violates the worker policy."""


class RealCodexAgent:
    def __init__(
        self,
        workspace_path: str,
        model_client: Any,
        *,
        platform_bus: Any | None = None,
        task_id: str | None = None,
        manifest_path: str | None = None,
        max_loops: int = 5,
    ) -> None:
        self.workspace = Path(workspace_path).expanduser().resolve(strict=True)
        if not self.workspace.is_dir():
            raise ValueError("workspace_path must be an existing directory")
        self.model_client = model_client
        self.platform_bus = platform_bus
        self.task_id = task_id
        self.max_loops = max(1, min(int(max_loops), 10))
        default_manifest = Path(__file__).with_name("manifest.json")
        self.manifest = self._load_manifest(Path(manifest_path) if manifest_path else default_manifest)
        self.changed_files: list[str] = []
        self.verification_commands: list[str] = []

    def run_task(self, objective: str) -> dict[str, Any]:
        """Run a bounded inspect/repair/verify loop with persisted state transitions."""
        objective = objective.strip()
        if not objective:
            raise ValueError("objective is required")

        self._transition("inspecting", "Codex worker started repository inspection.")
        history = [{"role": "system", "content": self._get_system_guidelines()}]
        current_prompt = f"Objective: {objective}\nBegin with one permitted action."

        try:
            for loop_idx in range(self.max_loops):
                history.append({"role": "user", "content": current_prompt})
                ai_response = str(self.model_client.generate(history))
                history.append({"role": "assistant", "content": ai_response})

                write_action = self._parse_write_file(ai_response)
                exec_action = self._parse_execute_command(ai_response)
                if write_action and exec_action:
                    raise AgentPolicyError("one response may request only one action")

                if write_action:
                    self._transition("repairing", f"Writing {write_action['path']}")
                    relative_path = self._write_file(write_action["path"], write_action["content"])
                    feedback = f"[SYSTEM FEEDBACK] wrote {relative_path}. Run verification next."
                elif exec_action:
                    self._transition("verifying", f"Running {exec_action['command']}")
                    result = self._execute_command(exec_action["command"])
                    feedback = self._command_feedback(result)
                    if result.returncode == 0:
                        verification_id = f"agent-{uuid.uuid4().hex}"
                        summary = (
                            f"Verified with: {exec_action['command']}\n"
                            f"Changed files: {', '.join(self.changed_files) or 'none'}\n"
                            f"Output: {result.stdout[-4000:]}"
                        )
                        self._transition("passed", summary, verification_id=verification_id)
                        return {
                            "status": "passed",
                            "verification_id": verification_id,
                            "changed_files": list(self.changed_files),
                            "command": exec_action["command"],
                            "output": result.stdout[-_MAX_OUTPUT_CHARS:],
                        }
                else:
                    current_prompt = (
                        "No executable action was supplied. The task is not complete. "
                        "Provide one permitted write or verification action."
                    )
                    continue

                current_prompt = f"Review this execution result and choose the next action:\n{feedback}"

            message = "Maximum self-correction loops reached without passing verification."
            self._transition("failed", message)
            return {"status": "failed", "message": message, "changed_files": self.changed_files}
        except Exception as exc:
            self._transition("failed", str(exc))
            raise

    def _load_manifest(self, path: Path) -> dict[str, Any]:
        data = json.loads(path.read_text(encoding="utf-8"))
        required = {"framework", "agent", "modes", "targets", "guardrails"}
        if not required.issubset(data):
            raise ValueError("agent manifest is missing required fields")
        required_guards = {"workspace_confinement", "verification_evidence"}
        if not required_guards.issubset(set(data["guardrails"])):
            raise ValueError("agent manifest lacks mandatory guardrails")
        return data

    def _resolve_write_path(self, raw_path: str) -> Path:
        candidate = (self.workspace / raw_path).resolve()
        try:
            relative = candidate.relative_to(self.workspace)
        except ValueError as exc:
            raise AgentPolicyError("write path escapes the assigned workspace") from exc
        if candidate == self.workspace or any(part in _PROTECTED_PARTS for part in relative.parts):
            raise AgentPolicyError("write path is protected")
        return candidate

    def _write_file(self, raw_path: str, content: str) -> str:
        encoded = content.encode("utf-8")
        if len(encoded) > _MAX_WRITE_BYTES:
            raise AgentPolicyError("file payload exceeds the worker size limit")
        target = self._resolve_write_path(raw_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.amosclaud-tmp")
        temporary.write_bytes(encoded)
        os.replace(temporary, target)
        relative = target.relative_to(self.workspace).as_posix()
        if relative not in self.changed_files:
            self.changed_files.append(relative)
        return relative

    def _execute_command(self, command: str) -> subprocess.CompletedProcess[str]:
        if any(token in command for token in ("\n", "\r", ";", "|", "&&", "||", ">", "<", "`", "$(")):
            raise AgentPolicyError("shell operators are not allowed")
        arguments = shlex.split(command)
        if not arguments or not any(tuple(arguments[: len(prefix)]) == prefix for prefix in _ALLOWED_COMMAND_PREFIXES):
            raise AgentPolicyError("command is not in the verification allowlist")
        result = subprocess.run(
            arguments,
            cwd=self.workspace,
            capture_output=True,
            text=True,
            timeout=120,
            shell=False,
            env={"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(self.workspace)},
            check=False,
        )
        self.verification_commands.append(command)
        return result

    def _transition(self, status: str, summary: str, *, verification_id: str | None = None) -> None:
        if self.platform_bus is None or not self.task_id:
            return
        payload: dict[str, Any] = {
            "task_id": self.task_id,
            "status": status,
            "result_summary": summary[:20_000],
        }
        if verification_id:
            payload["verification_id"] = verification_id
        frame = self.platform_bus.frame("platform.job.transition", payload)
        self.platform_bus.execute(frame)

    @staticmethod
    def _command_feedback(result: subprocess.CompletedProcess[str]) -> str:
        stdout = result.stdout[-_MAX_OUTPUT_CHARS:]
        stderr = result.stderr[-_MAX_OUTPUT_CHARS:]
        return (
            f"[SYSTEM RESULT] exit={result.returncode}\n"
            f"STDOUT:\n{stdout}\nSTDERR:\n{stderr}"
        )

    def _get_system_guidelines(self) -> str:
        return (
            "You are the Amosclaud verified software worker. Request exactly one action per reply.\n"
            "Write files only with: ```write:relative/path.py\nCONTENT\n```\n"
            "Run verification only with: ```execute\npython -m pytest -q\n```\n"
            "Allowed tools are compileall, pytest, flake8, and ruff check. "
            "Never access credentials, workflows, .git, networks, git push, or merge operations. "
            "A task is complete only after an allowed verification command exits with code 0."
        )

    @staticmethod
    def _parse_write_file(text: str) -> dict[str, str] | None:
        matches = re.findall(r"```write:([^\n]+)\n(.*?)```", text, re.DOTALL)
        if len(matches) > 1:
            raise AgentPolicyError("multiple write actions are not allowed")
        if matches:
            path, content = matches[0]
            return {"path": path.strip(), "content": content}
        return None

    @staticmethod
    def _parse_execute_command(text: str) -> dict[str, str] | None:
        matches = re.findall(r"```execute\n(.*?)```", text, re.DOTALL)
        if len(matches) > 1:
            raise AgentPolicyError("multiple execute actions are not allowed")
        if matches:
            return {"command": matches[0].strip()}
        return None

"""Restricted command execution for deterministic verification."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


class RuntimeExecutor:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()

    def _run(self, command: list[str], timeout: int = 120) -> dict[str, object]:
        result = subprocess.run(
            command,
            cwd=self.workspace,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        output = (result.stdout + "\n" + result.stderr).strip()
        return {
            "command": " ".join(command),
            "passed": result.returncode == 0,
            "exit_code": result.returncode,
            "summary": output.splitlines()[-1] if output else "No output",
            "output": output[-12000:],
        }

    def verify(self) -> list[dict[str, object]]:
        checks: list[dict[str, object]] = []
        checks.append(self._run([sys.executable, "-m", "compileall", "-q", "src"], 60))
        if (self.workspace / "tests").exists():
            checks.append(self._run([sys.executable, "-m", "pytest", "-q"], 120))
        return checks

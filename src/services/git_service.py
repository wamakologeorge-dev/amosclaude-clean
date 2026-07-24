"""Controlled Git operations used only through the central Autonomous orchestrator."""

from __future__ import annotations

import subprocess
from pathlib import Path


class GitService:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()

    def status(self) -> str:
        result = subprocess.run(["git", "status", "--short"], cwd=self.workspace, text=True, capture_output=True, check=False)
        return result.stdout.strip()

    def create_branch(self, name: str, *, authorized: bool) -> None:
        if not authorized:
            raise PermissionError("Branch creation requires authorization")
        subprocess.run(["git", "switch", "-c", name], cwd=self.workspace, check=True)

    def commit(self, message: str, *, authorized: bool) -> None:
        if not authorized:
            raise PermissionError("Commit creation requires authorization")
        subprocess.run(["git", "add", "--all"], cwd=self.workspace, check=True)
        subprocess.run(["git", "commit", "-m", message], cwd=self.workspace, check=True)

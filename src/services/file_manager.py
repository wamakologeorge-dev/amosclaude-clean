"""Safe file operations constrained to the authorized workspace."""

from __future__ import annotations

from pathlib import Path


class SafeFileManager:
    PROTECTED = {".git", ".env", "data", "secrets"}

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()

    def resolve(self, relative_path: str) -> Path:
        path = (self.workspace / relative_path).resolve()
        if self.workspace not in path.parents and path != self.workspace:
            raise PermissionError("Path escapes the controlled workspace")
        if any(part in self.PROTECTED for part in path.relative_to(self.workspace).parts):
            raise PermissionError("Protected path cannot be modified by Autonomous")
        return path

    def read(self, relative_path: str) -> str:
        return self.resolve(relative_path).read_text(encoding="utf-8")

    def write(self, relative_path: str, content: str, *, authorized: bool) -> None:
        if not authorized:
            raise PermissionError("Explicit write authorization is required")
        path = self.resolve(relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def delete(self, relative_path: str, *, authorized: bool) -> None:
        if not authorized:
            raise PermissionError("Explicit delete authorization is required")
        self.resolve(relative_path).unlink()

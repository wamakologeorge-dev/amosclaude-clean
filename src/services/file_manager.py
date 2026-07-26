"""Safe file operations constrained to the authorized workspace."""

from __future__ import annotations

from pathlib import Path


class SafeFileManager:
    PROTECTED_PARTS = {".git", ".env", "data", "secrets", "credentials"}
    PROTECTED_PREFIXES = (
        ".github/workflows/",
        ".github/actions/",
    )
    PROTECTED_FILES = {
        "SECURITY.md",
        ".github/SECURITY.md",
        "CODEOWNERS",
        ".github/CODEOWNERS",
        "Dockerfile",
        "railway.json",
        "vercel.json",
    }

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()

    def resolve(self, relative_path: str) -> Path:
        normalized = str(relative_path or "").strip().replace("\\", "/")
        if not normalized:
            raise PermissionError("An explicit relative path is required")
        path = (self.workspace / normalized).resolve()
        if self.workspace not in path.parents and path != self.workspace:
            raise PermissionError("Path escapes the controlled workspace")
        relative = path.relative_to(self.workspace).as_posix()
        if any(part in self.PROTECTED_PARTS for part in Path(relative).parts):
            raise PermissionError("Protected path cannot be modified by Autonomous")
        if relative in self.PROTECTED_FILES or any(
            relative.startswith(prefix) for prefix in self.PROTECTED_PREFIXES
        ):
            raise PermissionError(
                "Protected repair-control files require a separate maintenance pull request"
            )
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

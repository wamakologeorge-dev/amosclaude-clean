"""Restricted command execution for deterministic repair verification."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


class RuntimeExecutor:
    """Run a bounded, repository-derived verification plan without shell=True."""

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()

    def _safe_workspace_relative_paths(
        self, changed_files: list[str] | None
    ) -> list[str]:
        safe_paths: list[str] = []
        for item in (changed_files or []):
            raw = str(item).strip().replace("\\", "/")
            if not raw:
                continue
            candidate = (self.workspace / raw).resolve()
            try:
                relative = candidate.relative_to(self.workspace)
            except ValueError:
                continue
            safe_paths.append(relative.as_posix())
        return safe_paths

    def _run(
        self,
        command: list[str],
        timeout: int = 120,
        *,
        name: str | None = None,
    ) -> dict[str, object]:
        try:
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
                "name": name or command[0],
                "command": " ".join(command),
                "passed": result.returncode == 0,
                "exit_code": result.returncode,
                "summary": output.splitlines()[-1] if output else "No output",
                "output": output[-12_000:],
            }
        except subprocess.TimeoutExpired as exc:
            return {
                "name": name or command[0],
                "command": " ".join(command),
                "passed": False,
                "exit_code": 124,
                "summary": f"Verification timed out after {timeout} seconds",
                "output": str(exc)[-12_000:],
            }
        except FileNotFoundError as exc:
            return {
                "name": name or command[0],
                "command": " ".join(command),
                "passed": False,
                "exit_code": 127,
                "summary": (
                    f"Verification executable is unavailable: {command[0]}"
                ),
                "output": str(exc),
            }

    def verification_commands(
        self, changed_files: list[str] | None = None
    ) -> list[tuple[str, list[str], int]]:
        normalized = self._safe_workspace_relative_paths(changed_files)
        commands: list[tuple[str, list[str], int]] = []
        if (self.workspace / ".git").exists():
            commands.append(("Git diff integrity", ["git", "diff", "--check"], 60))

        python_files = [
            item
            for item in normalized
            if item.endswith(".py") and (self.workspace / item).is_file()
        ]
        if python_files:
            commands.append(
                (
                    "Python compilation",
                    [sys.executable, "-m", "py_compile", *python_files],
                    90,
                )
            )

        selected_tests: list[str] = []
        for item in python_files:
            path = Path(item)
            name = path.name
            if (
                item.startswith("tests/")
                or name.startswith("test_")
                or name.endswith("_test.py")
            ):
                selected_tests.append(item)
                continue
            stem = path.stem
            for candidate in (
                self.workspace / "tests" / f"test_{stem}.py",
                self.workspace / "tests" / f"{stem}_test.py",
            ):
                if candidate.is_file():
                    selected_tests.append(
                        candidate.relative_to(self.workspace).as_posix()
                    )

        selected_tests = list(dict.fromkeys(selected_tests))
        if selected_tests:
            commands.append(
                (
                    "Focused pytest",
                    [sys.executable, "-m", "pytest", "-q", *selected_tests],
                    300,
                )
            )
        elif (self.workspace / "tests").is_dir():
            commands.append(
                (
                    "Repository pytest",
                    [sys.executable, "-m", "pytest", "-q"],
                    300,
                )
            )
        return commands

    def verify(
        self, changed_files: list[str] | None = None
    ) -> list[dict[str, object]]:
        return [
            self._run(command, timeout, name=name)
            for name, command, timeout in self.verification_commands(changed_files)
        ]

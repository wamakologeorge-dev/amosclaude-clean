"""Container-isolated command execution for deterministic repair verification."""

from __future__ import annotations

import json
import os
import shlex
from pathlib import Path
from typing import Any, Callable

from amoscloud_ai.isolated_runner import (
    IsolatedRunResult,
    RunnerConfigurationError,
    UnsafeCommandError,
    run_in_isolated_container,
)

ContainerRunner = Callable[..., IsolatedRunResult]


class RuntimeExecutor:
    """Run repository-derived checks in a locked-down ephemeral container.

    Verification fails closed when the isolated runner is unavailable or rejects a
    command. There is deliberately no host-process fallback.
    """

    def __init__(
        self,
        workspace: Path,
        *,
        runner: ContainerRunner = run_in_isolated_container,
    ) -> None:
        allowed_root = Path(os.getenv("AMOSCLAUD_WORKSPACE_ROOT", ".")).resolve()
        resolved_workspace = workspace.resolve()
        if (
            resolved_workspace != allowed_root
            and allowed_root not in resolved_workspace.parents
        ):
            raise ValueError("Workspace escapes allowed root")
        self.workspace = resolved_workspace
        self.runner = runner

    def _safe_workspace_relative_paths(
        self, changed_files: list[str] | None
    ) -> list[str]:
        safe_paths: list[str] = []
        for item in changed_files or []:
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

    @staticmethod
    def _summary(output: str) -> str:
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        return lines[-1] if lines else "No output"

    def _run(
        self,
        command: list[str],
        timeout: int = 120,
        *,
        name: str | None = None,
    ) -> dict[str, object]:
        command_text = shlex.join(command)
        runner_command = command
        if command[:3] == ["git", "diff", "--check"]:
            runner_command = [
                "python",
                "-c",
                (
                    "import subprocess,sys; "
                    "sys.exit(subprocess.run(['git','diff','--check']).returncode)"
                ),
            ]
        runner_command_text = shlex.join(runner_command)
        check_name = name or command[0]
        environment = {
            "CI": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "npm_config_audit": "false",
            "npm_config_fund": "false",
        }
        try:
            result = self.runner(
                runner_command_text,
                workspace=self.workspace,
                environment=environment,
                timeout_seconds=timeout,
            )
            output = str(result.output or "").strip()
            return {
                "name": check_name,
                "command": command_text,
                "passed": result.returncode == 0,
                "exit_code": result.returncode,
                "summary": self._summary(output),
                "output": output[-12_000:],
                "isolated": True,
                "runtime": "docker",
                "timed_out": bool(result.timed_out),
            }
        except (RunnerConfigurationError, UnsafeCommandError) as exc:
            output = f"Isolated verification blocked: {type(exc).__name__}: {exc}"
            return {
                "name": check_name,
                "command": command_text,
                "passed": False,
                "exit_code": 126,
                "summary": output,
                "output": output,
                "isolated": True,
                "runtime": "docker",
                "timed_out": False,
            }
        except Exception as exc:  # pragma: no cover - final fail-closed boundary
            output = f"Isolated verification stopped safely: {type(exc).__name__}: {exc}"
            return {
                "name": check_name,
                "command": command_text,
                "passed": False,
                "exit_code": 125,
                "summary": output,
                "output": output,
                "isolated": True,
                "runtime": "docker",
                "timed_out": False,
            }

    def _package_scripts(self) -> dict[str, str]:
        allowed_root = Path(os.getenv("AMOSCLAUD_WORKSPACE_ROOT", ".")).resolve()
        workspace = self.workspace.resolve()
        if workspace != allowed_root and allowed_root not in workspace.parents:
            return {}
        package = (workspace / "package.json").resolve()
        if package != workspace and workspace not in package.parents:
            return {}
        if not package.is_file():
            return {}
        try:
            payload: Any = json.loads(package.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        scripts = payload.get("scripts", {}) if isinstance(payload, dict) else {}
        if not isinstance(scripts, dict):
            return {}
        return {
            str(name): str(value)
            for name, value in scripts.items()
            if isinstance(name, str) and isinstance(value, str)
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
                    ["python", "-m", "py_compile", *python_files],
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
                    ["python", "-m", "pytest", "-q", *selected_tests],
                    300,
                )
            )
        elif (self.workspace / "tests").is_dir():
            commands.append(
                (
                    "Repository pytest",
                    ["python", "-m", "pytest", "-q"],
                    300,
                )
            )

        frontend_suffixes = {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"}
        frontend_metadata = {
            "package.json",
            "package-lock.json",
            "pnpm-lock.yaml",
            "yarn.lock",
        }
        frontend_changed = any(
            Path(item).suffix.lower() in frontend_suffixes or item in frontend_metadata
            for item in normalized
        )
        if frontend_changed:
            scripts = self._package_scripts()
            if "typecheck" in scripts:
                commands.append(
                    ("Frontend typecheck", ["npm", "run", "typecheck"], 300)
                )
            if "test" in scripts:
                commands.append(("Frontend tests", ["npm", "test"], 300))
            if "build" in scripts:
                commands.append(("Frontend build", ["npm", "run", "build"], 600))

        return commands

    def verify(
        self, changed_files: list[str] | None = None
    ) -> list[dict[str, object]]:
        return [
            self._run(command, timeout, name=name)
            for name, command, timeout in self.verification_commands(changed_files)
        ]

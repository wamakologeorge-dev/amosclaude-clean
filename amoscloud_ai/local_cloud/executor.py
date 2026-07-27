"""Bounded folder-to-production execution without an arbitrary command endpoint."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from .workspaces import Workspace


class ExecutionError(RuntimeError):
    """Raised when a local action is unsafe or cannot be executed."""


@dataclass
class Job:
    id: str
    workspace_id: str
    action: str
    status: str
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    exit_code: int | None = None
    output: str = ""


class LocalJobManager:
    """Run a fixed action catalog in registered folders, never caller-provided shell."""

    ACTIONS = {
        "inspect": "Read git status and repository metadata.",
        "verify_python": "Compile Python files and run pytest when available.",
        "docker_build": "Build a local production Docker image.",
        "docker_compose_up": "Start the repository through Docker Compose.",
    }

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def required_confirmation(workspace_id: str, action: str) -> str:
        return f"RUN {workspace_id} {action}"

    @staticmethod
    def _run(command: list[str], *, cwd: Path, timeout: int) -> tuple[int, str]:
        completed = subprocess.run(
            command,
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={
                **os.environ,
                "CI": "1",
                "PYTHONUNBUFFERED": "1",
            },
        )
        output = (completed.stdout + "\n" + completed.stderr).strip()
        return completed.returncode, output[-50_000:]

    def _commands(self, action: str, workspace: Workspace) -> list[tuple[list[str], int]]:
        root = Path(workspace.path)
        if action == "inspect":
            commands: list[tuple[list[str], int]] = []
            if (root / ".git").exists() and shutil.which("git"):
                commands.append((["git", "status", "--short", "--branch"], 60))
            commands.append(
                (
                    [
                        sys.executable,
                        "-c",
                        (
                            "import json,pathlib; p=pathlib.Path('.'); "
                            "print(json.dumps({'root':str(p.resolve()),"
                            "'entries':sorted(x.name for x in p.iterdir())[:200]}))"
                        ),
                    ],
                    60,
                )
            )
            return commands
        if action == "verify_python":
            commands = [([sys.executable, "-m", "compileall", "-q", "."], 600)]
            if (root / "tests").is_dir():
                commands.append(([sys.executable, "-m", "pytest", "-q"], 1800))
            return commands
        if action == "docker_build":
            if not shutil.which("docker"):
                raise ExecutionError("Docker is not installed")
            if not (root / "Dockerfile").is_file():
                raise ExecutionError("Workspace has no Dockerfile")
            image = f"amosclaud-local/{workspace.id}:latest"
            return [(["docker", "build", "--tag", image, "."], 3600)]
        if action == "docker_compose_up":
            if not shutil.which("docker"):
                raise ExecutionError("Docker is not installed")
            if not any(
                (root / name).is_file()
                for name in (
                    "compose.yml",
                    "compose.yaml",
                    "docker-compose.yml",
                    "docker-compose.yaml",
                )
            ):
                raise ExecutionError("Workspace has no Docker Compose file")
            return [(["docker", "compose", "up", "--detach", "--build"], 3600)]
        raise ExecutionError("Unsupported local action")

    def _execute(self, job_id: str, workspace: Workspace) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.status = "running"
            job.started_at = self._utc_now()
        outputs: list[str] = []
        exit_code = 0
        try:
            for command, timeout in self._commands(job.action, workspace):
                code, output = self._run(
                    command,
                    cwd=Path(workspace.path),
                    timeout=timeout,
                )
                outputs.append(f"$ {' '.join(command)}\n{output}".strip())
                if code != 0:
                    exit_code = code
                    break
            status = "succeeded" if exit_code == 0 else "failed"
        except (ExecutionError, OSError, subprocess.SubprocessError) as exc:
            status = "failed"
            exit_code = 1
            outputs.append(f"{type(exc).__name__}: {exc}")
        with self._lock:
            job = self._jobs[job_id]
            job.status = status
            job.exit_code = exit_code
            job.output = "\n\n".join(outputs)[-50_000:]
            job.finished_at = self._utc_now()

    def create(
        self,
        *,
        workspace: Workspace,
        action: str,
        confirmation: str,
    ) -> Job:
        if action not in self.ACTIONS:
            raise ExecutionError("Unsupported local action")
        expected = self.required_confirmation(workspace.id, action)
        if confirmation.strip() != expected:
            raise ExecutionError(f"Confirmation must exactly equal: {expected}")
        job = Job(
            id=f"job_{uuid.uuid4().hex}",
            workspace_id=workspace.id,
            action=action,
            status="queued",
            created_at=self._utc_now(),
        )
        with self._lock:
            self._jobs[job.id] = job
        thread = threading.Thread(
            target=self._execute,
            args=(job.id, workspace),
            name=f"amosclaud-local-{job.id}",
            daemon=True,
        )
        thread.start()
        return job

    def get(self, job_id: str) -> Job:
        with self._lock:
            try:
                return self._jobs[job_id]
            except KeyError as exc:
                raise ExecutionError("Job was not found") from exc

    def list(self) -> list[dict[str, object]]:
        with self._lock:
            return [asdict(job) for job in reversed(list(self._jobs.values()))]

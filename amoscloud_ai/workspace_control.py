"""Control an installed Amosclaud workspace without exposing repository internals."""

from __future__ import annotations

import argparse
import json
import os
import shutil

# Only the resolved Docker executable is called; shell execution is never enabled.
import subprocess  # nosec B404
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


class WorkspaceError(RuntimeError):
    pass


@dataclass(frozen=True)
class WorkspaceLayout:
    root: Path
    app: Path
    projects: Path
    config: Path
    data: Path
    logs: Path


def discover_layout(start: Path | None = None) -> WorkspaceLayout:
    location = (start or Path.cwd()).resolve()
    candidates = [location, *location.parents]
    root = next(
        (
            candidate
            for candidate in candidates
            if (candidate / "app" / "docker-compose.selfhost.yml").is_file()
        ),
        None,
    )
    if root:
        app = root / "app"
        projects = root / "workspace" / "projects"
    else:
        root = next(
            (
                candidate
                for candidate in candidates
                if (candidate / "docker-compose.selfhost.yml").is_file()
            ),
            None,
        )
        if not root:
            raise WorkspaceError("Run this command from an Amosclaud installation")
        app = root
        projects = root / "AmosclaudWorkspace"
    return WorkspaceLayout(
        root=root,
        app=app,
        projects=projects,
        config=root / "config",
        data=root / "data",
        logs=root / "logs",
    )


def ensure_layout(layout: WorkspaceLayout) -> None:
    for directory in (
        layout.projects,
        layout.config,
        layout.data,
        layout.logs,
    ):
        directory.mkdir(parents=True, exist_ok=True)


def _compose(layout: WorkspaceLayout, *arguments: str, check: bool = True) -> int:
    docker = shutil.which("docker")
    if not docker:
        raise WorkspaceError("Docker is not installed or is not available on PATH")
    # The executable is resolved and arguments come from fixed CLI choices.
    completed = subprocess.run(  # nosec B603
        [
            docker,
            "compose",
            "-f",
            str(layout.app / "docker-compose.selfhost.yml"),
            *arguments,
        ],
        cwd=layout.app,
        check=check,
    )
    return completed.returncode


def _runner_profile(layout: WorkspaceLayout) -> tuple[str, ...]:
    runner_env = layout.app / ".env.runner"
    if runner_env.is_file() and "AMOSCLAUD_RUNNER_ID=" in runner_env.read_text(encoding="utf-8"):
        return ("--profile", "connected-runner")
    return ()


def doctor(layout: WorkspaceLayout) -> dict:
    ensure_layout(layout)
    docker = shutil.which("docker")
    report = {
        "workspace_root": str(layout.root),
        "application_found": (layout.app / "Dockerfile").is_file(),
        "configuration_found": (layout.app / ".env").is_file(),
        "docker_found": bool(docker),
        "projects_directory": str(layout.projects),
        "projects_writable": os.access(layout.projects, os.W_OK),
    }
    if docker:
        report["docker_ready"] = (
            subprocess.run(  # nosec B603
                [docker, "info"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            ).returncode
            == 0
        )
    else:
        report["docker_ready"] = False
    report["ready"] = all(
        report[key]
        for key in (
            "application_found",
            "configuration_found",
            "docker_found",
            "docker_ready",
            "projects_writable",
        )
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(prog="amosclaud-workspace")
    parser.add_argument(
        "command",
        choices=["doctor", "start", "stop", "status", "logs"],
        nargs="?",
        default="doctor",
    )
    args = parser.parse_args()
    try:
        layout = discover_layout()
        ensure_layout(layout)
        if args.command == "doctor":
            print(json.dumps(doctor(layout), indent=2))
        elif args.command == "start":
            _compose(layout, *_runner_profile(layout), "up", "-d")
        elif args.command == "stop":
            _compose(layout, "down")
        elif args.command == "status":
            _compose(layout, "ps")
        elif args.command == "logs":
            _compose(layout, "logs", "--tail", "200")
    except WorkspaceError as exc:
        print(f"Amosclaud workspace error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Short local entry point for Amosclaud tests, builds, and guarded repairs."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Sequence

from amoscloud_ai.local_cloud.agent_guard import (
    AgentBuildGuard,
    AgentGuardError,
    model_from_environment,
)


def _workspace(value: str) -> Path:
    path = Path(value).expanduser().resolve(strict=True)
    if not path.is_dir():
        raise argparse.ArgumentTypeError("workspace must be an existing directory")
    return path


def _run(command: Sequence[str], workspace: Path, timeout: int) -> int:
    try:
        completed = subprocess.run(
            list(command),
            cwd=workspace,
            env={**os.environ, "CI": "1", "PYTHONUNBUFFERED": "1"},
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return completed.returncode


def _test_command(workspace: Path) -> list[str]:
    script = (
        "import compileall,pathlib,subprocess,sys; "
        "ok=compileall.compile_dir('.',quiet=1); "
        "sys.exit(1) if not ok else None; "
        "raise SystemExit(subprocess.call([sys.executable,'-m','pytest','-q']) "
        "if pathlib.Path('tests').is_dir() else 0)"
    )
    return [sys.executable, "-c", script]


def _image_name(workspace: Path) -> str:
    cleaned = re.sub(r"[^a-z0-9_.-]+", "-", workspace.name.lower()).strip("-.")
    return f"amosclaud-local/{cleaned or 'workspace'}:latest"


def _build_command(workspace: Path) -> list[str]:
    if not shutil.which("docker"):
        raise AgentGuardError("Docker is not installed or is not on PATH")
    if not (workspace / "Dockerfile").is_file():
        raise AgentGuardError("The workspace has no Dockerfile")
    return ["docker", "build", "--tag", _image_name(workspace), "."]


def _guard(
    workspace: Path,
    command: Sequence[str],
    *,
    label: str,
    timeout: int,
) -> int:
    result = AgentBuildGuard(
        workspace,
        model_from_environment(),
        maximum_attempts=3,
    ).run(command, label=label, timeout=timeout)
    print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    return 0 if result.status == "succeeded" else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="amosclaud",
        description="Run bounded local Amosclaud verification and build actions.",
    )
    parser.add_argument(
        "action",
        choices=("test", "guard-test", "build", "guard-build", "serve"),
    )
    parser.add_argument(
        "--workspace",
        type=_workspace,
        default=Path.cwd(),
        help="Existing workspace directory; defaults to the current directory.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    workspace = Path(args.workspace).resolve(strict=True)
    try:
        if args.action == "serve":
            from scripts.run_local_cloud import main as run_local_cloud

            run_local_cloud()
            return 0
        if args.action == "test":
            return _run(_test_command(workspace), workspace, 1800)
        if args.action == "guard-test":
            return _guard(
                workspace,
                _test_command(workspace),
                label="guarded Python verification",
                timeout=1800,
            )
        command = _build_command(workspace)
        if args.action == "build":
            return _run(command, workspace, 3600)
        return _guard(
            workspace,
            command,
            label="guarded Docker build",
            timeout=3600,
        )
    except AgentGuardError as exc:
        print(f"Agent guard blocked the action: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

"""Cross-platform task runner for the complete Amosclaud workspace."""

from __future__ import annotations

import argparse
import shutil

# Tasks use fixed argument lists and never enable shell execution.
import subprocess  # nosec B404
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable


class TaskFailure(RuntimeError):
    pass


def run(*arguments: str) -> None:
    completed = subprocess.run(list(arguments), cwd=ROOT, check=False)  # nosec B603
    if completed.returncode:
        raise TaskFailure(f"Command failed ({completed.returncode}): {' '.join(arguments)}")


def setup() -> None:
    run(PYTHON, "-m", "pip", "install", "--upgrade", "pip")
    run(PYTHON, "-m", "pip", "install", "-r", "requirements-dev.txt")
    run(PYTHON, "-m", "pip", "install", "-e", ".")


def build() -> None:
    shutil.rmtree(ROOT / "dist", ignore_errors=True)
    shutil.rmtree(ROOT / "build", ignore_errors=True)
    run(PYTHON, "-m", "build")


def test() -> None:
    run(PYTHON, "-m", "pytest", "-q")


def quality() -> None:
    run(PYTHON, "-m", "black", "--check", "amoscloud_ai", "tests", "scripts")
    run(PYTHON, "-m", "flake8", "amoscloud_ai", "tests", "scripts")
    run(PYTHON, "-m", "bandit", "-q", "-r", "amoscloud_ai")


def package() -> None:
    build()
    run(
        PYTHON,
        "-m",
        "pytest",
        "-q",
        "tests/test_workspace_control.py",
        "tests/test_virtual_memory.py",
    )


TASKS = {
    "setup": setup,
    "build": build,
    "test": test,
    "quality": quality,
    "package": package,
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Build and validate Amosclaud")
    parser.add_argument("task", choices=sorted(TASKS))
    args = parser.parse_args()
    try:
        TASKS[args.task]()
    except TaskFailure as exc:
        print(f"Amosclaud task failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()

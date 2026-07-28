"""Fast, deterministic checks for changed pull-request files.

The complete repository workflows remain authoritative. This module provides a
small feedback lane that avoids importing or installing the full Amosclaud
runtime.
"""

from __future__ import annotations

import argparse
import ast
import subprocess
import sys
from pathlib import Path
from typing import Iterable, Sequence

import yaml

REPOSITORY_BEHAVIOR_PATHS = {
    ".github/scripts/repository_behavior.py",
    ".github/workflows/behavior-automation.yml",
    "tests/test_repository_behavior_automation.py",
}
FAST_TESTS = ("tests/test_fast_pr_gate.py",)
REPOSITORY_BEHAVIOR_TEST = "tests/test_repository_behavior_automation.py"
MERGE_MARKERS = ("<<<<<<< ", "=======", ">>>>>>> ")


class FastGateError(RuntimeError):
    """Raised when a deterministic changed-file check fails."""


def _run(command: Sequence[str], *, cwd: Path) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def changed_paths(base: str, head: str, *, cwd: Path) -> tuple[str, ...]:
    result = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=ACMR", f"{base}...{head}"],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return tuple(line.strip() for line in result.stdout.splitlines() if line.strip())


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise FastGateError(f"{path} is not valid UTF-8") from exc


def validate_python(path: Path) -> None:
    source = _read_text(path)
    if any(marker in source for marker in MERGE_MARKERS):
        raise FastGateError(f"{path} contains an unresolved merge marker")
    try:
        ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        raise FastGateError(f"{path}:{exc.lineno}: {exc.msg}") from exc


def validate_yaml(path: Path) -> None:
    source = _read_text(path)
    if any(marker in source for marker in MERGE_MARKERS):
        raise FastGateError(f"{path} contains an unresolved merge marker")
    try:
        yaml.safe_load(source)
    except yaml.YAMLError as exc:
        raise FastGateError(f"{path} is not valid YAML: {exc}") from exc


def select_fast_tests(paths: Iterable[str], *, root: Path) -> tuple[str, ...]:
    changed = set(paths)
    tests = list(FAST_TESTS)
    if changed & REPOSITORY_BEHAVIOR_PATHS:
        tests.append(REPOSITORY_BEHAVIOR_TEST)
    return tuple(test for test in dict.fromkeys(tests) if (root / test).is_file())


def run_gate(paths: Sequence[str], *, root: Path) -> None:
    existing = [path for path in paths if (root / path).is_file()]
    python_files = sorted(path for path in existing if path.endswith(".py"))
    yaml_files = sorted(path for path in existing if path.endswith((".yml", ".yaml")))

    for relative in python_files:
        validate_python(root / relative)
    for relative in yaml_files:
        validate_yaml(root / relative)

    if python_files:
        _run(["black", "--check", "--diff", *python_files], cwd=root)
        _run(["isort", "--check-only", "--diff", *python_files], cwd=root)

    tests = select_fast_tests(existing, root=root)
    if tests:
        _run([sys.executable, "-m", "pytest", "-q", *tests], cwd=root)

    print(
        f"Fast gate passed: {len(python_files)} Python files, "
        f"{len(yaml_files)} YAML files, {len(tests)} focused test files."
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", help="Base commit SHA for git diff")
    parser.add_argument("--head", help="Head commit SHA for git diff")
    parser.add_argument(
        "--file",
        action="append",
        default=[],
        help="Explicit changed path; may be supplied more than once",
    )
    parser.add_argument("--root", default=".", help="Repository root")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.root).resolve()
    paths = tuple(args.file)
    if not paths:
        if not args.base or not args.head:
            raise SystemExit("provide --base and --head, or at least one --file")
        paths = changed_paths(args.base, args.head, cwd=root)
    try:
        run_gate(paths, root=root)
    except (FastGateError, subprocess.CalledProcessError) as exc:
        print(f"fast gate failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

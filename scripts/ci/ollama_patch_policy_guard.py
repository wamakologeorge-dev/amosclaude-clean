#!/usr/bin/env python3
"""Enforce legacy patch aliases as native Ollama-only repair routes."""

from __future__ import annotations

import sys
from pathlib import Path

DISPATCHER = ".github/workflows/amosclaud-claude-patch.yml"
WORKER = ".github/workflows/amosclaud-claude-patch-worker.yml"
PARSER = ".github/scripts/parse_comment.py"
EXECUTOR = ".github/scripts/ai_patch_executor.py"
POLICY_MARKER = "AMOSCLAUD-OLLAMA-PATCH-CONTRACT:v2"
PROTECTED_FILES = (
    DISPATCHER,
    WORKER,
    PARSER,
    EXECUTOR,
    "scripts/ci/ollama_patch_policy_guard.py",
    "tests/test_parse_comment_script.py",
    "tests/test_ai_patch_executor.py",
    "tests/test_claude_patch_policy_guard.py",
    "docs/AMOSCLAUD_CLAUDE_PATCH_EXECUTOR.md",
)


def _read(root: Path, relative: str, errors: list[str]) -> str:
    path = root / relative
    if not path.is_file():
        errors.append(f"missing Ollama patch contract file: {relative}")
        return ""
    return path.read_text(encoding="utf-8")


def _require(text: str, required: tuple[str, ...], label: str, errors: list[str]) -> None:
    for value in required:
        if value not in text:
            errors.append(f"{label} is missing contract: {value}")


def _forbid(text: str, forbidden: tuple[str, ...], label: str, errors: list[str]) -> None:
    for value in forbidden:
        if value in text:
            errors.append(f"{label} contains forbidden external-model authority: {value}")


def validate_repository(root: Path) -> list[str]:
    root = root.resolve()
    errors: list[str] = []
    for relative in PROTECTED_FILES:
        _read(root, relative, errors)

    dispatcher = _read(root, DISPATCHER, errors)
    worker = _read(root, WORKER, errors)
    parser = _read(root, PARSER, errors)
    executor = _read(root, EXECUTOR, errors)
    documentation = _read(root, "docs/AMOSCLAUD_CLAUDE_PATCH_EXECUTOR.md", errors)

    _require(
        dispatcher,
        (
            "name: Amosclaud Ollama Patch Dispatcher",
            "ref: ${{ github.event.repository.default_branch }}",
            "persist-credentials: false",
            "python trusted/.github/scripts/parse_comment.py",
            "gh workflow run amosclaud-repair-control-plane.yml",
            '-f provider="ollama-cloud"',
            "head_ref != default_branch",
            'test -n "$objective"',
        ),
        "Ollama dispatcher",
        errors,
    )
    _forbid(
        dispatcher,
        (
            "ANTHROPIC_API_KEY",
            "ANTHROPIC_MODEL",
            "api.anthropic.com",
            "ai_patch_executor.py",
            "amosclaud-claude-patch-worker.yml",
            "pull_request_target",
            "GITHUB_APP_PRIVATE_KEY",
        ),
        "Ollama dispatcher",
        errors,
    )

    _require(
        worker,
        (
            "name: Amosclaud Ollama Patch Compatibility Worker",
            "gh workflow run amosclaud-repair-control-plane.yml",
            '-f provider="ollama-cloud"',
            'head_ref != os.environ["DEFAULT_BRANCH"]',
            'current == os.environ["EXPECTED_HEAD_SHA"].lower()',
        ),
        "Ollama compatibility worker",
        errors,
    )
    _forbid(
        worker,
        (
            "ANTHROPIC_API_KEY",
            "ANTHROPIC_MODEL",
            "api.anthropic.com",
            "GITHUB_APP_PRIVATE_KEY",
            "git push",
            "git commit",
            "pull_request_target",
        ),
        "Ollama compatibility worker",
        errors,
    )

    _require(
        parser,
        (
            'frozenset({"patch", "ai-fix", "claude-fix"})',
            'source_format == "ollama-patch-alias"',
            "and bool(compact_objective)",
            "association in WRITE_ASSOCIATIONS",
            'payload["objective"] = "[stored locally]"',
        ),
        "comment parser",
        errors,
    )
    _forbid(parser, ("claude-patch-alias",), "comment parser", errors)

    _require(
        executor,
        (
            'STATUS = "NATIVE_OLLAMA_REPAIR_REQUIRED"',
            '"provider": "amosclaud-native-ollama"',
            '"patch_applied": False',
            '"commit_allowed": False',
            '"push_allowed": False',
        ),
        "retired executor",
        errors,
    )
    _forbid(
        executor,
        (
            "ANTHROPIC_API_KEY",
            "ANTHROPIC_MODEL",
            "api.anthropic.com",
            "urllib.request",
            "git apply",
            "git commit",
            "git push",
        ),
        "retired executor",
        errors,
    )

    if POLICY_MARKER not in documentation:
        errors.append("Ollama patch documentation is missing the policy marker")
    _forbid(
        documentation,
        ("ANTHROPIC_API_KEY", "api.anthropic.com", "Anthropic Messages API"),
        "Ollama patch documentation",
        errors,
    )
    return sorted(set(errors))


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    errors = validate_repository(root)
    if errors:
        print("Amosclaud Ollama patch policy: FAILED")
        for error in errors:
            print(f"- {error}")
        return 1
    print(f"Amosclaud Ollama patch policy: PASSED ({POLICY_MARKER})")
    print(f"Protected Ollama patch files: {len(PROTECTED_FILES)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

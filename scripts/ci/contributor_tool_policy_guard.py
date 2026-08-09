#!/usr/bin/env python3
"""Enforce the permanent Amosclaud-first contributor tool policy."""

from __future__ import annotations

import sys
from pathlib import Path

POLICY_MARKER = "AMOSCLAUD-TOOL-SOVEREIGNTY-POLICY:v1"
CODE_OWNER = "@wamakologeorge-dev"

PROTECTED_FILES = (
    "docs/CONTRIBUTOR_TOOL_POLICY.md",
    "AGENTS.md",
    ".github/PULL_REQUEST_TEMPLATE.md",
    ".github/CODEOWNERS",
    ".github/workflows/policy.yml",
    "scripts/ci/contributor_tool_policy_guard.py",
    "tests/test_contributor_tool_policy_guard.py",
)

CANONICAL_REQUIREMENTS = (
    "Scan the Amosclaud repository first.",
    "Reuse or extend Amosclaud’s existing capability.",
    "Use an external tool only when Amosclaud has no suitable equivalent.",
    "This policy must not be removed, weakened, bypassed",
    "Amosclaud Workflow Policy / policy",
)

AGENT_REQUIREMENTS = (
    POLICY_MARKER,
    "Scan the Amosclaud repository first",
    "Reuse or extend the existing Amosclaud capability",
    "External tools are permitted only when no suitable Amosclaud equivalent exists",
)

PULL_REQUEST_REQUIREMENTS = (
    POLICY_MARKER,
    "Amosclaud-first tool scan",
    "Existing Amosclaud capability reused or extended",
    "External dependency exception evidence",
)

WORKFLOW_REQUIREMENTS = (
    "python scripts/ci/contributor_tool_policy_guard.py",
    "Enforce contributor tool sovereignty",
)


def _read(root: Path, relative_path: str, errors: list[str]) -> str:
    path = root / relative_path
    if not path.is_file():
        errors.append(f"missing protected policy file: {relative_path}")
        return ""
    return path.read_text(encoding="utf-8")


def validate_repository(root: Path) -> list[str]:
    """Return every policy-contract violation found under *root*."""

    root = root.resolve()
    errors: list[str] = []

    for relative_path in PROTECTED_FILES:
        _read(root, relative_path, errors)

    canonical = _read(root, "docs/CONTRIBUTOR_TOOL_POLICY.md", errors)
    for requirement in (POLICY_MARKER, *CANONICAL_REQUIREMENTS):
        if requirement not in canonical:
            errors.append(f"canonical policy is missing required text: {requirement}")

    agents = _read(root, "AGENTS.md", errors)
    for requirement in AGENT_REQUIREMENTS:
        if requirement not in agents:
            errors.append(f"AGENTS.md is missing required policy text: {requirement}")

    template = _read(root, ".github/PULL_REQUEST_TEMPLATE.md", errors)
    for requirement in PULL_REQUEST_REQUIREMENTS:
        if requirement not in template:
            errors.append(
                f"pull-request template is missing required policy text: {requirement}"
            )

    workflow = _read(root, ".github/workflows/policy.yml", errors)
    for requirement in WORKFLOW_REQUIREMENTS:
        if requirement not in workflow:
            errors.append(f"policy workflow is missing enforcement: {requirement}")
    for relative_path in PROTECTED_FILES:
        if relative_path not in workflow:
            errors.append(
                f"policy workflow does not trigger when protected file changes: {relative_path}"
            )

    codeowners = _read(root, ".github/CODEOWNERS", errors)
    for relative_path in PROTECTED_FILES:
        expected = f"/{relative_path} {CODE_OWNER}"
        if expected not in codeowners:
            errors.append(f"CODEOWNERS is missing protected entry: {expected}")

    return sorted(set(errors))


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    errors = validate_repository(root)
    if errors:
        print("Amosclaud contributor tool policy: FAILED")
        for error in errors:
            print(f"- {error}")
        return 1

    print(f"Amosclaud contributor tool policy: PASSED ({POLICY_MARKER})")
    print(f"Protected policy files: {len(PROTECTED_FILES)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

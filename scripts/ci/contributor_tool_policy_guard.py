#!/usr/bin/env python3
"""Enforce the permanent Amosclaud-first contributor tool policy."""

from __future__ import annotations

import shlex
import sys
from collections.abc import Mapping
from pathlib import Path

import yaml

POLICY_MARKER = "AMOSCLAUD-TOOL-SOVEREIGNTY-POLICY:v1"
CODE_OWNER = "@wamakologeorge-dev"
POLICY_COMMAND = "python scripts/ci/contributor_tool_policy_guard.py"
POLICY_STEP_NAME = "Enforce contributor tool sovereignty"

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


def _read(root: Path, relative_path: str, errors: list[str]) -> str:
    path = root / relative_path
    if not path.is_file():
        errors.append(f"missing protected policy file: {relative_path}")
        return ""
    return path.read_text(encoding="utf-8")


def _load_workflow(root: Path, errors: list[str]) -> Mapping[str, object]:
    text = _read(root, ".github/workflows/policy.yml", errors)
    if not text:
        return {}
    try:
        payload = yaml.safe_load(text)
    except yaml.YAMLError:
        errors.append("policy workflow is not valid YAML")
        return {}
    if not isinstance(payload, Mapping):
        errors.append("policy workflow must be a mapping")
        return {}
    return payload


def _pull_request_trigger(payload: Mapping[str, object], errors: list[str]) -> None:
    events = payload.get("on", payload.get(True))
    if isinstance(events, str):
        pull_request_config: object = None if events == "pull_request" else False
    elif isinstance(events, list):
        pull_request_config = None if "pull_request" in events else False
    elif isinstance(events, Mapping):
        pull_request_config = events.get("pull_request", False)
    else:
        pull_request_config = False

    if pull_request_config is False:
        errors.append("policy workflow must run on every pull_request")
        return
    if isinstance(pull_request_config, Mapping) and any(
        key in pull_request_config for key in ("paths", "paths-ignore")
    ):
        errors.append("policy workflow pull_request trigger must not use path filters")


def _active_shell_commands(script: str) -> set[str]:
    commands: set[str] = set()
    for raw_line in script.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        commands.add(line)
    return commands


def _workflow_enforcement(payload: Mapping[str, object], errors: list[str]) -> None:
    jobs = payload.get("jobs")
    policy = jobs.get("policy") if isinstance(jobs, Mapping) else None
    steps = policy.get("steps") if isinstance(policy, Mapping) else None
    if not isinstance(steps, list):
        errors.append("policy workflow is missing jobs.policy.steps")
        return

    matching_steps = [
        step
        for step in steps
        if isinstance(step, Mapping) and step.get("name") == POLICY_STEP_NAME
    ]
    if len(matching_steps) != 1:
        errors.append("policy workflow must contain exactly one effective sovereignty step")
        return
    run = matching_steps[0].get("run")
    commands = _active_shell_commands(str(run or ""))
    if POLICY_COMMAND not in commands:
        errors.append("policy workflow sovereignty step does not execute the policy guard")


def _codeowner_rules(text: str) -> dict[str, tuple[str, ...]]:
    rules: dict[str, tuple[str, ...]] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            parts = shlex.split(line, comments=True, posix=True)
        except ValueError:
            continue
        if len(parts) >= 2:
            rules[parts[0]] = tuple(parts[1:])
    return rules


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
            errors.append(f"pull-request template is missing required policy text: {requirement}")

    workflow = _load_workflow(root, errors)
    _pull_request_trigger(workflow, errors)
    _workflow_enforcement(workflow, errors)

    codeowners = _codeowner_rules(_read(root, ".github/CODEOWNERS", errors))
    for relative_path in PROTECTED_FILES:
        pattern = f"/{relative_path}"
        owners = codeowners.get(pattern, ())
        if CODE_OWNER not in owners:
            errors.append(f"CODEOWNERS is missing effective protected entry: {pattern}")

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

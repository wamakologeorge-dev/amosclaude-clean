#!/usr/bin/env python3
"""Enforce permanent Amosclaud-first contributor and automation policy."""

from __future__ import annotations

import ast
import shlex
import sys
from collections.abc import Mapping
from pathlib import Path

import yaml

POLICY_MARKER = "AMOSCLAUD-TOOL-SOVEREIGNTY-POLICY:v1"
CODE_OWNER = "@wamakologeorge-dev"
POLICY_COMMAND = "python scripts/ci/contributor_tool_policy_guard.py"
POLICY_STEP_NAME = "Enforce contributor tool sovereignty"
REVIEW_COMMAND = "python -m amosclaud_bot.review_publisher"
SECURITY_BRIDGE_COMMAND = "python -m amoscloud_ai.security_repair_bridge"
REPAIR_WORKFLOW = "amosclaud-repair-control-plane.yml"
APPROVED_SECURITY_WORKFLOWS = {
    "CodeQL",
    "Amosclaud Dependency Threat Gate",
    "Fortify AST Scan",
}

PROTECTED_FILES = (
    "docs/CONTRIBUTOR_TOOL_POLICY.md",
    "AGENTS.md",
    ".github/PULL_REQUEST_TEMPLATE.md",
    ".github/CODEOWNERS",
    ".github/workflows/policy.yml",
    "scripts/ci/contributor_tool_policy_guard.py",
    "tests/test_contributor_tool_policy_guard.py",
    ".github/workflows/amosclaud-bot-review.yml",
    "amosclaud_bot/review_publisher.py",
    "tests/test_amosclaud_review_publisher.py",
    "docs/AMOSCLAUD_BOT_FORMAL_REVIEW.md",
    ".github/workflows/codeql.yml",
    ".github/workflows/fortify.yml",
    ".github/workflows/amosclaud-dependency-threat-gate.yml",
    ".github/workflows/amosclaud-security-repair-bridge.yml",
    "scripts/ci/advanced_security_gate.py",
    "amoscloud_ai/github_app_connection.py",
    "amoscloud_ai/security_repair_bridge.py",
    "tests/test_advanced_security_gate.py",
    "tests/test_github_app_connection.py",
    "tests/test_security_repair_bridge.py",
    "docs/AMOSCLAUD_SECURITY_REPAIR_LOOP.md",
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


def _load_yaml(root: Path, relative_path: str, errors: list[str]) -> Mapping[str, object]:
    text = _read(root, relative_path, errors)
    if not text:
        return {}
    try:
        payload = yaml.safe_load(text)
    except yaml.YAMLError:
        errors.append(f"workflow is not valid YAML: {relative_path}")
        return {}
    if not isinstance(payload, Mapping):
        errors.append(f"workflow must be a mapping: {relative_path}")
        return {}
    return payload


def _events(payload: Mapping[str, object]) -> object:
    return payload.get("on", payload.get(True))


def _event_config(payload: Mapping[str, object], event_name: str) -> object:
    events = _events(payload)
    if isinstance(events, str):
        return None if events == event_name else False
    if isinstance(events, list):
        return None if event_name in events else False
    if isinstance(events, Mapping):
        return events.get(event_name, False)
    return False


def _pull_request_trigger(payload: Mapping[str, object], errors: list[str]) -> None:
    pull_request_config = _event_config(payload, "pull_request")
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


def _steps(payload: Mapping[str, object], job_name: str) -> list[Mapping[str, object]]:
    jobs = payload.get("jobs")
    job = jobs.get(job_name) if isinstance(jobs, Mapping) else None
    raw_steps = job.get("steps") if isinstance(job, Mapping) else None
    if not isinstance(raw_steps, list):
        return []
    return [step for step in raw_steps if isinstance(step, Mapping)]


def _workflow_enforcement(payload: Mapping[str, object], errors: list[str]) -> None:
    steps = _steps(payload, "policy")
    if not steps:
        errors.append("policy workflow is missing jobs.policy.steps")
        return

    matching_steps = [step for step in steps if step.get("name") == POLICY_STEP_NAME]
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


def _permissions(payload: Mapping[str, object], job_name: str | None = None) -> Mapping[str, object]:
    if job_name is None:
        permissions = payload.get("permissions")
    else:
        jobs = payload.get("jobs")
        job = jobs.get(job_name) if isinstance(jobs, Mapping) else None
        permissions = job.get("permissions") if isinstance(job, Mapping) else None
    return permissions if isinstance(permissions, Mapping) else {}


def _checkout_is_trusted(steps: list[Mapping[str, object]]) -> bool:
    for step in steps:
        uses = str(step.get("uses") or "")
        if not uses.startswith("actions/checkout@"):
            continue
        settings = step.get("with")
        if not isinstance(settings, Mapping):
            return False
        ref = str(settings.get("ref") or "")
        persist = settings.get("persist-credentials")
        if "github.event.repository.default_branch" in ref and persist is False:
            return True
    return False


def _commands_include(steps: list[Mapping[str, object]], command: str) -> bool:
    return any(command in _active_shell_commands(str(step.get("run") or "")) for step in steps)


def _review_events(source: str, errors: list[str]) -> set[str]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        errors.append("review publisher is not valid Python")
        return set()

    values: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values):
            if not isinstance(key, ast.Constant) or key.value != "event":
                continue
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                values.add(value.value)
            else:
                values.add("<dynamic>")
    return values


def _review_contract(root: Path, errors: list[str]) -> None:
    path = ".github/workflows/amosclaud-bot-review.yml"
    workflow = _load_yaml(root, path, errors)
    if _event_config(workflow, "issue_comment") is False:
        errors.append("formal review workflow must use issue_comment")

    permissions = _permissions(workflow)
    expected = {
        "contents": "read",
        "checks": "read",
        "issues": "write",
        "pull-requests": "write",
    }
    if dict(permissions) != expected:
        errors.append("formal review workflow permissions must remain least-privilege")

    steps = _steps(workflow, "formal-review")
    if not _checkout_is_trusted(steps):
        errors.append("formal review workflow must check out the trusted default branch")
    if not _commands_include(steps, REVIEW_COMMAND):
        errors.append("formal review workflow does not execute the Amosclaud review publisher")

    workflow_text = _read(root, path, errors)
    if "pull_request_target" in workflow_text or "secrets." in workflow_text:
        errors.append("formal review workflow must not use pull_request_target or protected secrets")

    events = _review_events(_read(root, "amosclaud_bot/review_publisher.py", errors), errors)
    if events != {"COMMENT"}:
        errors.append("formal review publisher must submit only GitHub COMMENT reviews")


def _workflow_run_names(payload: Mapping[str, object]) -> set[str]:
    config = _event_config(payload, "workflow_run")
    workflows = config.get("workflows") if isinstance(config, Mapping) else None
    if not isinstance(workflows, list):
        return set()
    return {str(item) for item in workflows}


def _security_contract(root: Path, errors: list[str]) -> None:
    codeql = _read(root, ".github/workflows/codeql.yml", errors)
    for required in (
        "queries: security-extended",
        "name: Every CodeQL alert is a threat",
        "security-events: read",
        "python scripts/ci/advanced_security_gate.py",
    ):
        if required not in codeql:
            errors.append(f"CodeQL threat gate is missing required text: {required}")

    dependency = _read(root, ".github/workflows/amosclaud-dependency-threat-gate.yml", errors)
    for required in (
        "fail-on-severity: low",
        "fail-on-scopes: development,runtime,unknown",
        "warn-only: false",
    ):
        if required not in dependency:
            errors.append(f"dependency threat gate is missing required text: {required}")

    fortify = _read(root, ".github/workflows/fortify.yml", errors)
    for required in (
        "Treat every AST security finding as a blocking threat",
        "python -m bandit -r src amoscloud_ai",
        "exit \"$scan_status\"",
    ):
        if required not in fortify:
            errors.append(f"AST threat gate is missing required text: {required}")

    bridge_path = ".github/workflows/amosclaud-security-repair-bridge.yml"
    bridge = _load_yaml(root, bridge_path, errors)
    if _workflow_run_names(bridge) != APPROVED_SECURITY_WORKFLOWS:
        errors.append("security repair bridge workflow source allowlist changed")
    bridge_steps = _steps(bridge, "route-security-repair")
    if not _checkout_is_trusted(bridge_steps):
        errors.append("security repair bridge must check out the trusted default branch")
    if not _commands_include(bridge_steps, SECURITY_BRIDGE_COMMAND):
        errors.append("security repair bridge does not execute the Amosclaud bridge module")
    bridge_text = _read(root, bridge_path, errors)
    if "pull_request_target" in bridge_text:
        errors.append("security repair bridge must not use pull_request_target")

    bridge_source = _read(root, "amoscloud_ai/security_repair_bridge.py", errors)
    for workflow in APPROVED_SECURITY_WORKFLOWS:
        if f'"{workflow}"' not in bridge_source:
            errors.append(f"security bridge source is missing approved workflow: {workflow}")
    if f'REPAIR_WORKFLOW = "{REPAIR_WORKFLOW}"' not in bridge_source:
        errors.append("security bridge repair target changed")
    for required in (
        "current_sha != head_sha",
        "without suppressing, dismissing, or weakening",
        '"REPAIR_DISPATCHED"',
        '"BLOCKED"',
    ):
        if required not in bridge_source:
            errors.append(f"security bridge is missing safety contract: {required}")

    app_connection = _read(root, "amoscloud_ai/github_app_connection.py", errors)
    for required in (
        "::add-mask::",
        "INSTALLATION_AUTHENTICATION_FAILED",
        "REPOSITORY_NOT_ACCESSIBLE",
        "BOT_USER_ID_MISMATCH",
    ):
        if required not in app_connection:
            errors.append(f"GitHub App connection is missing safety contract: {required}")


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

    workflow = _load_yaml(root, ".github/workflows/policy.yml", errors)
    _pull_request_trigger(workflow, errors)
    _workflow_enforcement(workflow, errors)
    _review_contract(root, errors)
    _security_contract(root, errors)

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

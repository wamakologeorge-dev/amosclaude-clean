#!/usr/bin/env python3
"""Enforce permanent Amosclaud-first contributor and automation policy."""

from __future__ import annotations

import ast
import shlex
import sys
from collections.abc import Mapping
from fnmatch import fnmatchcase
from pathlib import Path

import yaml

POLICY_MARKER = "AMOSCLAUD-TOOL-SOVEREIGNTY-POLICY:v1"
CODE_OWNER = "@wamakologeorge-dev"
POLICY_COMMAND = "python scripts/ci/contributor_tool_policy_guard.py"
POLICY_STEP_NAME = "Enforce contributor tool sovereignty"
REVIEW_COMMAND = "python -m amosclaud_bot.review_publisher"
CODEQL_GATE_COMMAND = "python trusted/scripts/ci/advanced_security_gate.py"
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
    "amosclaud_bot/status_board.py",
    "tests/test_amosclaud_status_board.py",
    "amoscloud_ai/bot_contributor_profile.py",
    ".github/workflows/codeql.yml",
    ".github/workflows/amosclaud-codeql-threat-gate.yml",
    ".github/workflows/fortify.yml",
    ".github/workflows/amosclaud-dependency-threat-gate.yml",
    ".github/workflows/amosclaud-security-repair-bridge.yml",
    "scripts/ci/advanced_security_gate.py",
    "scripts/ci/bandit_pr_gate.py",
    "amoscloud_ai/github_app_connection.py",
    "amoscloud_ai/security_repair_bridge.py",
    "tests/test_advanced_security_gate.py",
    "tests/test_bandit_pr_gate.py",
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


def _event_config(payload: Mapping[str, object], event_name: str) -> object:
    events = payload.get("on", payload.get(True))
    if isinstance(events, str):
        return None if events == event_name else False
    if isinstance(events, list):
        return None if event_name in events else False
    if isinstance(events, Mapping):
        return events.get(event_name, False)
    return False


def _job(payload: Mapping[str, object], job_name: str) -> Mapping[str, object]:
    jobs = payload.get("jobs")
    value = jobs.get(job_name) if isinstance(jobs, Mapping) else None
    return value if isinstance(value, Mapping) else {}


def _steps(payload: Mapping[str, object], job_name: str) -> list[Mapping[str, object]]:
    value = _job(payload, job_name).get("steps")
    if not isinstance(value, list):
        return []
    return [step for step in value if isinstance(step, Mapping)]


def _active_shell_commands(script: str) -> set[str]:
    return {
        line
        for raw_line in script.splitlines()
        if (line := raw_line.strip()) and not line.startswith("#")
    }


def _commands_include(steps: list[Mapping[str, object]], command: str) -> bool:
    return any(
        command in active
        for step in steps
        for active in _active_shell_commands(str(step.get("run") or ""))
    )


def _workflow_enforcement(payload: Mapping[str, object], errors: list[str]) -> None:
    pull_request = _event_config(payload, "pull_request")
    if pull_request is False:
        errors.append("policy workflow must run on every pull_request")
    elif isinstance(pull_request, Mapping) and any(
        key in pull_request for key in ("paths", "paths-ignore")
    ):
        errors.append("policy workflow pull_request trigger must not use path filters")

    policy_job = _job(payload, "policy")
    if not policy_job:
        errors.append("policy workflow is missing jobs.policy")
        return
    if "if" in policy_job:
        errors.append("policy workflow job must not be conditional")

    matching = [step for step in _steps(payload, "policy") if step.get("name") == POLICY_STEP_NAME]
    if len(matching) != 1:
        errors.append("policy workflow must contain exactly one effective sovereignty step")
        return
    if "if" in matching[0]:
        errors.append("policy workflow sovereignty step must not be conditional")
    if not any(
        POLICY_COMMAND in command
        for command in _active_shell_commands(str(matching[0].get("run") or ""))
    ):
        errors.append("policy workflow sovereignty step does not execute the policy guard")


def _codeowner_rules(text: str) -> list[tuple[str, tuple[str, ...]]]:
    rules: list[tuple[str, tuple[str, ...]]] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            parts = shlex.split(line, comments=True, posix=True)
        except ValueError:
            continue
        if len(parts) >= 2:
            rules.append((parts[0], tuple(parts[1:])))
    return rules


def _codeowner_pattern_matches(pattern: str, relative_path: str) -> bool:
    path = relative_path.lstrip("/")
    candidate = pattern.strip()
    if not candidate or candidate.startswith("!"):
        return False
    anchored = candidate.startswith("/")
    candidate = candidate.lstrip("/")
    if candidate in {"*", "**", "**/*"}:
        return True
    if candidate.endswith("/**"):
        prefix = candidate[:-3].rstrip("/")
        return path == prefix or path.startswith(f"{prefix}/")
    if candidate.endswith("/"):
        prefix = candidate.rstrip("/")
        return path == prefix or path.startswith(f"{prefix}/")
    if anchored or "/" in candidate:
        return fnmatchcase(path, candidate)
    return any(fnmatchcase(part, candidate) for part in path.split("/"))


def _effective_codeowners(
    rules: list[tuple[str, tuple[str, ...]]], relative_path: str
) -> tuple[str, ...]:
    owners: tuple[str, ...] = ()
    for pattern, candidate_owners in rules:
        if _codeowner_pattern_matches(pattern, relative_path):
            owners = candidate_owners
    return owners


def _permissions(
    payload: Mapping[str, object], job_name: str | None = None
) -> Mapping[str, object]:
    value = (
        payload.get("permissions")
        if job_name is None
        else _job(payload, job_name).get("permissions")
    )
    return value if isinstance(value, Mapping) else {}


def _checkout_is_trusted(steps: list[Mapping[str, object]]) -> bool:
    for step in steps:
        if not str(step.get("uses") or "").startswith("actions/checkout@"):
            continue
        settings = step.get("with")
        if not isinstance(settings, Mapping):
            return False
        ref = str(settings.get("ref") or "")
        if (
            "github.event.repository.default_branch" in ref
            and settings.get("persist-credentials") is False
        ):
            return True
    return False


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
            if isinstance(key, ast.Constant) and key.value == "event":
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
    expected_permissions = {
        "contents": "read",
        "checks": "read",
        "issues": "write",
        "pull-requests": "write",
    }
    if dict(_permissions(workflow)) != expected_permissions:
        errors.append("formal review workflow permissions must remain least-privilege")

    review_job = _job(workflow, "formal-review")
    condition = str(review_job.get("if") or "")
    for required in (
        "github.event.issue.pull_request",
        "@amosclaud review",
        "@amosclaud-bot review",
    ):
        if required not in condition:
            errors.append(f"formal review job filter is missing: {required}")

    steps = _steps(workflow, "formal-review")
    if not _checkout_is_trusted(steps):
        errors.append("formal review workflow must check out the trusted default branch")
    if not _commands_include(steps, REVIEW_COMMAND):
        errors.append("formal review workflow does not execute the Amosclaud review publisher")
    workflow_text = _read(root, path, errors)
    if "pull_request_target" in workflow_text or "secrets." in workflow_text:
        errors.append(
            "formal review workflow must not use pull_request_target or protected secrets"
        )

    publisher = _read(root, "amosclaud_bot/review_publisher.py", errors)
    if _review_events(publisher, errors) != {"COMMENT"}:
        errors.append("formal review publisher must submit only GitHub COMMENT reviews")
    for required in (
        "METADATA AND CHECK EVIDENCE ONLY",
        'base.replace("**APPROVE**", "**NEEDS HUMAN REVIEW**")',
        'base.replace("**NEEDS HUMAN REVIEW**", "**CHANGES REQUESTED**")',
        "_pending_checks(checks)",
    ):
        if required not in publisher:
            errors.append(f"formal review publisher is missing truthful coverage rule: {required}")


def _status_contract(root: Path, errors: list[str]) -> None:
    source = _read(root, "amosclaud_bot/status_board.py", errors)
    for required in (
        "_REQUIRED_PULL_REQUEST_WORKFLOWS",
        "_REQUIRED_DEFAULT_BRANCH_WORKFLOWS",
        'quote(branch, safe="")',
        'frozenset({"pull_request", "workflow_run"})',
        "[required workflow]",
    ):
        if required not in source:
            errors.append(f"status board is missing truthful health contract: {required}")


def _workflow_run_names(payload: Mapping[str, object]) -> set[str]:
    config = _event_config(payload, "workflow_run")
    workflows = config.get("workflows") if isinstance(config, Mapping) else None
    return {str(item) for item in workflows} if isinstance(workflows, list) else set()


def _security_contract(root: Path, errors: list[str]) -> None:
    codeql = _read(root, ".github/workflows/codeql.yml", errors)
    for required in ("queries: security-extended", "security-events: write"):
        if required not in codeql:
            errors.append(f"CodeQL analysis is missing required text: {required}")
    for forbidden in ("security-events: read", "advanced_security_gate.py"):
        if forbidden in codeql:
            errors.append(f"CodeQL analysis contains trusted-gate logic: {forbidden}")

    codeql_gate_path = ".github/workflows/amosclaud-codeql-threat-gate.yml"
    codeql_gate = _load_yaml(root, codeql_gate_path, errors)
    if _workflow_run_names(codeql_gate) != {"CodeQL"}:
        errors.append("trusted CodeQL gate workflow source changed")
    expected_permissions = {"contents": "read", "security-events": "read"}
    if dict(_permissions(codeql_gate)) != expected_permissions:
        errors.append("trusted CodeQL gate permissions must remain least-privilege")
    condition = str(_job(codeql_gate, "codeql-threat-gate").get("if") or "")
    for required in (
        "github.event.workflow_run.event == 'pull_request'",
        "github.event.workflow_run.conclusion == 'success'",
    ):
        if required not in condition:
            errors.append(f"trusted CodeQL gate condition is missing: {required}")
    steps = _steps(codeql_gate, "codeql-threat-gate")
    if not _checkout_is_trusted(steps):
        errors.append("trusted CodeQL gate must check out the trusted default branch")
    if not _commands_include(steps, CODEQL_GATE_COMMAND):
        errors.append("trusted CodeQL gate does not execute the trusted alert evaluator")
    if not _commands_include(steps, SECURITY_BRIDGE_COMMAND):
        errors.append("trusted CodeQL gate does not route threats through Amosclaud")
    gate_text = _read(root, codeql_gate_path, errors)
    for required in (
        "Keep the pull request blocked until threats are cleared",
        "GITHUB_APP_PRIVATE_KEY",
    ):
        if required not in gate_text:
            errors.append(f"trusted CodeQL gate is missing repair contract: {required}")
    for forbidden in ("pull_request_target", "github.event.pull_request.head"):
        if forbidden in gate_text:
            errors.append(f"trusted CodeQL gate contains untrusted checkout input: {forbidden}")

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
        "name: Every new AST finding is a threat",
        "github.event.pull_request.base.sha",
        "github.event.pull_request.head.sha",
        '"bandit==1.9.4"',
        "python head/scripts/ci/bandit_pr_gate.py",
        "Full repository AST security debt audit",
    ):
        if required not in fortify:
            errors.append(f"AST threat gate is missing required text: {required}")
    for forbidden in ("--skip", "--exclude", "# nosec"):
        if forbidden in fortify:
            errors.append(f"AST threat gate contains a forbidden suppression: {forbidden}")

    bandit_gate = _read(root, "scripts/ci/bandit_pr_gate.py", errors)
    for required in (
        "every AST finding introduced by the exact head revision is blocking",
        '"THREATS_DETECTED"',
        "Counter(finding.fingerprint for finding in base)",
    ):
        if required not in bandit_gate:
            errors.append(f"differential AST gate is missing required contract: {required}")

    bridge_path = ".github/workflows/amosclaud-security-repair-bridge.yml"
    bridge = _load_yaml(root, bridge_path, errors)
    if _workflow_run_names(bridge) != APPROVED_SECURITY_WORKFLOWS:
        errors.append("security repair bridge workflow source allowlist changed")
    bridge_steps = _steps(bridge, "route-security-repair")
    if not _checkout_is_trusted(bridge_steps):
        errors.append("security repair bridge must check out the trusted default branch")
    if not _commands_include(bridge_steps, SECURITY_BRIDGE_COMMAND):
        errors.append("security repair bridge does not execute the Amosclaud bridge module")
    if "pull_request_target" in _read(root, bridge_path, errors):
        errors.append("security repair bridge must not use pull_request_target")

    bridge_source = _read(root, "amoscloud_ai/security_repair_bridge.py", errors)
    for workflow in APPROVED_SECURITY_WORKFLOWS:
        if f'"{workflow}"' not in bridge_source:
            errors.append(f"security bridge source is missing approved workflow: {workflow}")
    if '"Amosclaud CodeQL Threat Gate"' in bridge_source:
        errors.append("security bridge must not accept second-level CodeQL gate runs")
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

    profile = _read(root, "amoscloud_ai/bot_contributor_profile.py", errors)
    if 'DEFAULT_APP_SLUG = "amosclaud-bot"' not in profile:
        errors.append("contributor profile default App slug is not canonical")


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
    _workflow_enforcement(workflow, errors)
    _review_contract(root, errors)
    _status_contract(root, errors)
    _security_contract(root, errors)

    rules = _codeowner_rules(_read(root, ".github/CODEOWNERS", errors))
    for relative_path in PROTECTED_FILES:
        if CODE_OWNER not in _effective_codeowners(rules, relative_path):
            errors.append(f"CODEOWNERS effective rule does not protect: /{relative_path}")
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

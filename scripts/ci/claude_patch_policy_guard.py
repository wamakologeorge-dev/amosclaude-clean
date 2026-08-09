#!/usr/bin/env python3
"""Enforce the trusted Claude patch-generation and publication contract."""

from __future__ import annotations

import sys
from collections.abc import Mapping
from pathlib import Path

import yaml

WORKFLOW = ".github/workflows/amosclaud-claude-patch.yml"
PARSER = ".github/scripts/parse_comment.py"
EXECUTOR = ".github/scripts/ai_patch_executor.py"
POLICY_MARKER = "AMOSCLAUD-CLAUDE-PATCH-CONTRACT:v1"
PROTECTED_FILES = (
    WORKFLOW,
    PARSER,
    EXECUTOR,
    "scripts/ci/claude_patch_policy_guard.py",
    "tests/test_parse_comment_script.py",
    "tests/test_ai_patch_executor.py",
    "tests/test_claude_patch_policy_guard.py",
    "docs/AMOSCLAUD_CLAUDE_PATCH_EXECUTOR.md",
)


def _read(root: Path, relative: str, errors: list[str]) -> str:
    path = root / relative
    if not path.is_file():
        errors.append(f"missing Claude patch contract file: {relative}")
        return ""
    return path.read_text(encoding="utf-8")


def _yaml(root: Path, relative: str, errors: list[str]) -> Mapping[str, object]:
    text = _read(root, relative, errors)
    if not text:
        return {}
    try:
        payload = yaml.safe_load(text)
    except yaml.YAMLError:
        errors.append(f"invalid YAML: {relative}")
        return {}
    if not isinstance(payload, Mapping):
        errors.append(f"workflow must be a mapping: {relative}")
        return {}
    return payload


def _steps(workflow: Mapping[str, object]) -> list[Mapping[str, object]]:
    jobs = workflow.get("jobs")
    job = jobs.get("generate-verify-publish") if isinstance(jobs, Mapping) else None
    raw = job.get("steps") if isinstance(job, Mapping) else None
    return [step for step in raw or [] if isinstance(step, Mapping)]


def _step(steps: list[Mapping[str, object]], name: str) -> Mapping[str, object]:
    return next((step for step in steps if step.get("name") == name), {})


def validate_repository(root: Path) -> list[str]:
    root = root.resolve()
    errors: list[str] = []
    for relative in PROTECTED_FILES:
        _read(root, relative, errors)

    workflow = _yaml(root, WORKFLOW, errors)
    workflow_text = _read(root, WORKFLOW, errors)
    parser = _read(root, PARSER, errors)
    executor = _read(root, EXECUTOR, errors)
    documentation = _read(root, "docs/AMOSCLAUD_CLAUDE_PATCH_EXECUTOR.md", errors)
    steps = _steps(workflow)

    events = workflow.get("on", workflow.get(True))
    issue_comment = events.get("issue_comment") if isinstance(events, Mapping) else None
    if not isinstance(issue_comment, Mapping) or issue_comment.get("types") != ["created"]:
        errors.append("Claude patch workflow must run only for newly created issue comments")

    expected_permissions = {
        "contents": "read",
        "issues": "write",
        "pull-requests": "write",
    }
    permissions = workflow.get("permissions")
    if not isinstance(permissions, Mapping) or dict(permissions) != expected_permissions:
        errors.append("Claude patch workflow permissions changed from the bounded contract")

    trusted_checkout = _step(steps, "Check out trusted default-branch control plane")
    trusted_with = trusted_checkout.get("with") if isinstance(trusted_checkout, Mapping) else None
    if not isinstance(trusted_with, Mapping):
        errors.append("trusted checkout configuration is missing")
    else:
        if trusted_with.get("ref") != "${{ github.event.repository.default_branch }}":
            errors.append("trusted control plane must check out the default branch")
        if trusted_with.get("path") != "trusted":
            errors.append("trusted control plane must use the isolated trusted path")
        if trusted_with.get("persist-credentials") is not False:
            errors.append("trusted checkout must not persist credentials")

    target_checkout = _step(steps, "Check out the exact pull-request head as untrusted input")
    target_with = target_checkout.get("with") if isinstance(target_checkout, Mapping) else None
    if not isinstance(target_with, Mapping):
        errors.append("untrusted target checkout configuration is missing")
    else:
        if target_with.get("ref") != "${{ steps.target.outputs.head_sha }}":
            errors.append("untrusted target checkout must use the exact resolved head SHA")
        if target_with.get("path") != "target":
            errors.append("untrusted pull-request files must stay in the target path")
        if target_with.get("persist-credentials") is not False:
            errors.append("untrusted target checkout must not persist credentials")

    required_workflow_text = (
        "python trusted/.github/scripts/parse_comment.py",
        "python trusted/.github/scripts/ai_patch_executor.py",
        "git -C target apply --check",
        "python trusted/.github/scripts/amosclaud_repair_verify.py",
        "env -u ANTHROPIC_API_KEY",
        "python -m amoscloud_ai.github_app_connection",
        'remote_sha="$(git -C target ls-remote origin',
        'if [ "$remote_sha" != "$EXPECTED_SHA" ]',
        'git -C target push origin "HEAD:refs/heads/${HEAD_REF}"',
        "All normal pull-request checks and reviews must pass before merge.",
    )
    for required in required_workflow_text:
        if required not in workflow_text:
            errors.append(f"Claude patch workflow is missing safety contract: {required}")

    for forbidden in (
        "pull_request_target",
        "--force",
        "--force-with-lease",
        "gh pr merge",
        "event: APPROVE",
        "REQUEST_CHANGES",
        "persist-credentials: true",
    ):
        if forbidden in workflow_text:
            errors.append(f"Claude patch workflow contains forbidden authority: {forbidden}")

    for required in (
        'frozenset({"patch", "ai-fix", "claude-fix"})',
        'source_format == "claude-patch-alias"',
        "association in WRITE_ASSOCIATIONS",
        'payload["objective"] = "[stored locally]"',
    ):
        if required not in parser:
            errors.append(f"comment parser is missing contract: {required}")

    for required in (
        "f\"{base_url.rstrip('/')}/v1/messages\"",
        '"x-api-key": api_key',
        '"anthropic-version": anthropic_version',
        "candidate.validate_patch(patch, policy, args.mode)",
        '["git", "apply", "--check", str(patch_path)]',
        '"patch_applied": False',
        '"commit_allowed": False',
        '"push_allowed": False',
    ):
        if required not in executor:
            errors.append(f"Claude executor is missing contract: {required}")

    for forbidden in (
        "git apply --whitespace=fix",
        "git commit",
        "git push",
        "gh pr merge",
        "dangerously-skip-permissions",
    ):
        if forbidden in executor:
            errors.append(f"Claude executor contains forbidden execution authority: {forbidden}")

    if POLICY_MARKER not in documentation:
        errors.append("Claude patch documentation is missing the policy marker")

    return sorted(set(errors))


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    errors = validate_repository(root)
    if errors:
        print("Amosclaud Claude patch policy: FAILED")
        for error in errors:
            print(f"- {error}")
        return 1
    print(f"Amosclaud Claude patch policy: PASSED ({POLICY_MARKER})")
    print(f"Protected Claude patch files: {len(PROTECTED_FILES)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

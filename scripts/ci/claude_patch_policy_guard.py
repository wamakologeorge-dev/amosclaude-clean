#!/usr/bin/env python3
"""Enforce the trusted Claude patch dispatch, verification, and publication contract."""

from __future__ import annotations

import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

DISPATCHER = ".github/workflows/amosclaud-claude-patch.yml"
WORKER = ".github/workflows/amosclaud-claude-patch-worker.yml"
WORKFLOW = DISPATCHER
PARSER = ".github/scripts/parse_comment.py"
EXECUTOR = ".github/scripts/ai_patch_executor.py"
POLICY_MARKER = "AMOSCLAUD-CLAUDE-PATCH-CONTRACT:v1"
PROTECTED_FILES = (
    DISPATCHER,
    WORKER,
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


def _events(workflow: Mapping[str, object]) -> object:
    return workflow.get("on", workflow.get(True))


def _event(workflow: Mapping[str, object], name: str) -> object:
    events = _events(workflow)
    if isinstance(events, str):
        return None if events == name else False
    if isinstance(events, list):
        return None if name in events else False
    if isinstance(events, Mapping):
        return events.get(name, False)
    return False


def _job(workflow: Mapping[str, object], name: str) -> Mapping[str, object]:
    jobs = workflow.get("jobs")
    value = jobs.get(name) if isinstance(jobs, Mapping) else None
    return value if isinstance(value, Mapping) else {}


def _steps(workflow: Mapping[str, object], job_name: str) -> list[Mapping[str, object]]:
    raw = _job(workflow, job_name).get("steps")
    return [step for step in raw or [] if isinstance(step, Mapping)]


def _step(steps: list[Mapping[str, object]], name: str) -> Mapping[str, object]:
    return next((step for step in steps if step.get("name") == name), {})


def _permissions(
    workflow: Mapping[str, object], job_name: str | None = None
) -> Mapping[str, object]:
    value = (
        workflow.get("permissions")
        if job_name is None
        else _job(workflow, job_name).get("permissions")
    )
    return value if isinstance(value, Mapping) else {}


def _trusted_checkout(
    workflow: Mapping[str, object],
    job_name: str,
    step_name: str,
    errors: list[str],
) -> None:
    checkout = _step(_steps(workflow, job_name), step_name)
    settings = checkout.get("with") if isinstance(checkout, Mapping) else None
    if not isinstance(settings, Mapping):
        errors.append(f"{step_name} configuration is missing")
        return
    if settings.get("ref") != "${{ github.event.repository.default_branch }}":
        errors.append(f"{step_name} must check out the trusted default branch")
    if settings.get("path") != "trusted":
        errors.append(f"{step_name} must use the isolated trusted path")
    if settings.get("persist-credentials") is not False:
        errors.append(f"{step_name} must not persist credentials")


def _contains(value: Any, needle: str) -> bool:
    if isinstance(value, str):
        return needle in value
    if isinstance(value, Mapping):
        return any(_contains(item, needle) for item in value.values())
    if isinstance(value, list):
        return any(_contains(item, needle) for item in value)
    return False


def validate_repository(root: Path) -> list[str]:
    root = root.resolve()
    errors: list[str] = []
    for relative in PROTECTED_FILES:
        _read(root, relative, errors)

    dispatcher = _yaml(root, DISPATCHER, errors)
    worker = _yaml(root, WORKER, errors)
    dispatcher_text = _read(root, DISPATCHER, errors)
    worker_text = _read(root, WORKER, errors)
    parser = _read(root, PARSER, errors)
    executor = _read(root, EXECUTOR, errors)
    documentation = _read(root, "docs/AMOSCLAUD_CLAUDE_PATCH_EXECUTOR.md", errors)

    issue_comment = _event(dispatcher, "issue_comment")
    if not isinstance(issue_comment, Mapping) or issue_comment.get("types") != ["created"]:
        errors.append("Claude dispatcher must run only for newly created issue comments")
    expected_dispatcher_permissions = {
        "actions": "write",
        "contents": "read",
        "issues": "write",
        "pull-requests": "read",
    }
    if dict(_permissions(dispatcher)) != expected_dispatcher_permissions:
        errors.append("Claude dispatcher permissions changed from the bounded contract")

    _trusted_checkout(
        dispatcher,
        "dispatch-patch-worker",
        "Check out trusted default-branch control plane",
        errors,
    )
    for required in (
        "python trusted/.github/scripts/parse_comment.py",
        "gh workflow run amosclaud-claude-patch-worker.yml",
        '-f expected_head_sha="$EXPECTED_HEAD_SHA"',
        "The comment workflow does not check out or execute pull-request code",
    ):
        if required not in dispatcher_text:
            errors.append(f"Claude dispatcher is missing safety contract: {required}")
    for forbidden in (
        "secrets.",
        "ai_patch_executor.py",
        "amosclaud_repair_verify.py",
        "github_app_connection",
        "GITHUB_APP_PRIVATE_KEY",
        "ANTHROPIC_API_KEY",
        "Check out the exact pull-request head",
        "github.event.pull_request.head",
        "pull_request_target",
    ):
        if forbidden in dispatcher_text:
            errors.append(f"Claude dispatcher contains forbidden privileged behavior: {forbidden}")

    workflow_dispatch = _event(worker, "workflow_dispatch")
    required_inputs = {"issue_number", "comment_id", "expected_head_sha"}
    inputs = workflow_dispatch.get("inputs") if isinstance(workflow_dispatch, Mapping) else None
    if not isinstance(inputs, Mapping) or set(inputs) != required_inputs:
        errors.append("Claude worker dispatch inputs changed from the immutable contract")
    if _event(worker, "issue_comment") is not False:
        errors.append("Claude worker must never run directly from issue_comment")
    if dict(_permissions(worker)) != {}:
        errors.append("Claude worker must deny permissions by default")

    expected_job_permissions = {
        "generate-candidate": {
            "contents": "read",
            "issues": "read",
            "pull-requests": "read",
        },
        "verify-candidate": {"contents": "read"},
        "publish-candidate": {"contents": "read", "pull-requests": "read"},
        "report-result": {"issues": "write"},
    }
    for job_name, expected in expected_job_permissions.items():
        if dict(_permissions(worker, job_name)) != expected:
            errors.append(f"Claude worker permissions changed for job: {job_name}")

    _trusted_checkout(
        worker,
        "generate-candidate",
        "Check out trusted default-branch control plane",
        errors,
    )
    _trusted_checkout(
        worker,
        "verify-candidate",
        "Check out trusted default-branch verifier",
        errors,
    )
    _trusted_checkout(
        worker,
        "publish-candidate",
        "Check out trusted default-branch publisher",
        errors,
    )

    for required in (
        "python trusted/.github/scripts/parse_comment.py",
        "python trusted/.github/scripts/ai_patch_executor.py",
        "ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}",
        "git -C target apply --check",
        "actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c",
        "env -u ANTHROPIC_API_KEY",
        "python trusted/.github/scripts/amosclaud_repair_verify.py",
        "python -m amoscloud_ai.github_app_connection",
        'test "$remote_sha" = "$EXPECTED_SHA"',
        'git -C target push origin "HEAD:refs/heads/${HEAD_REF}"',
        "All normal pull-request checks and reviews must pass before merge.",
    ):
        if required not in worker_text:
            errors.append(f"Claude worker is missing safety contract: {required}")

    for forbidden in (
        "pull_request_target",
        "--force",
        "--force-with-lease",
        "gh pr merge",
        "event: APPROVE",
        "REQUEST_CHANGES",
        "persist-credentials: true",
    ):
        if forbidden in dispatcher_text or forbidden in worker_text:
            errors.append(f"Claude patch workflows contain forbidden authority: {forbidden}")

    generate = _job(worker, "generate-candidate")
    verify = _job(worker, "verify-candidate")
    publish = _job(worker, "publish-candidate")
    if _contains(generate, "GITHUB_APP_PRIVATE_KEY"):
        errors.append("candidate generation must not receive the GitHub App private key")
    if _contains(verify, "${{ secrets."):
        errors.append("credential-free verification must not receive protected secrets")
    if _contains(publish, "ANTHROPIC_API_KEY"):
        errors.append("publication must not receive the Claude API key")

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

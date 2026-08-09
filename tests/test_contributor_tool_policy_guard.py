from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUARD_PATH = ROOT / "scripts" / "ci" / "contributor_tool_policy_guard.py"


def _load_guard():
    spec = importlib.util.spec_from_file_location("contributor_tool_policy_guard", GUARD_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _copy_contract(tmp_path: Path, guard) -> Path:
    root = tmp_path / "repository"
    for relative_path in guard.PROTECTED_FILES:
        source = ROOT / relative_path
        destination = root / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    return root


def test_repository_policy_contract_is_intact() -> None:
    guard = _load_guard()

    assert guard.validate_repository(ROOT) == []


def test_removing_policy_marker_is_rejected(tmp_path: Path) -> None:
    guard = _load_guard()
    root = _copy_contract(tmp_path, guard)
    policy = root / "docs" / "CONTRIBUTOR_TOOL_POLICY.md"
    policy.write_text(
        policy.read_text(encoding="utf-8").replace(guard.POLICY_MARKER, "REMOVED"),
        encoding="utf-8",
    )

    errors = guard.validate_repository(root)

    assert any("canonical policy is missing required text" in error for error in errors)


def test_removing_code_owner_protection_is_rejected(tmp_path: Path) -> None:
    guard = _load_guard()
    root = _copy_contract(tmp_path, guard)
    codeowners = root / ".github" / "CODEOWNERS"
    protected_line = f"/docs/CONTRIBUTOR_TOOL_POLICY.md {guard.CODE_OWNER}"
    codeowners.write_text(
        codeowners.read_text(encoding="utf-8").replace(protected_line, ""),
        encoding="utf-8",
    )

    errors = guard.validate_repository(root)

    assert any("CODEOWNERS is missing effective protected entry" in error for error in errors)


def test_commenting_out_code_owner_protection_is_rejected(tmp_path: Path) -> None:
    guard = _load_guard()
    root = _copy_contract(tmp_path, guard)
    codeowners = root / ".github" / "CODEOWNERS"
    protected_line = f"/docs/CONTRIBUTOR_TOOL_POLICY.md {guard.CODE_OWNER}"
    codeowners.write_text(
        codeowners.read_text(encoding="utf-8").replace(
            protected_line,
            f"# {protected_line}",
        ),
        encoding="utf-8",
    )

    errors = guard.validate_repository(root)

    assert any("CODEOWNERS is missing effective protected entry" in error for error in errors)


def test_removing_workflow_guard_invocation_is_rejected(tmp_path: Path) -> None:
    guard = _load_guard()
    root = _copy_contract(tmp_path, guard)
    workflow = root / ".github" / "workflows" / "policy.yml"
    workflow.write_text(
        workflow.read_text(encoding="utf-8").replace(
            guard.POLICY_COMMAND,
            "echo policy guard removed",
        ),
        encoding="utf-8",
    )

    errors = guard.validate_repository(root)

    assert any("does not execute the policy guard" in error for error in errors)


def test_commented_workflow_guard_invocation_is_rejected(tmp_path: Path) -> None:
    guard = _load_guard()
    root = _copy_contract(tmp_path, guard)
    workflow = root / ".github" / "workflows" / "policy.yml"
    workflow.write_text(
        workflow.read_text(encoding="utf-8").replace(
            guard.POLICY_COMMAND,
            f"# {guard.POLICY_COMMAND}",
        ),
        encoding="utf-8",
    )

    errors = guard.validate_repository(root)

    assert any("does not execute the policy guard" in error for error in errors)


def test_renaming_effective_policy_step_is_rejected(tmp_path: Path) -> None:
    guard = _load_guard()
    root = _copy_contract(tmp_path, guard)
    workflow = root / ".github" / "workflows" / "policy.yml"
    workflow.write_text(
        workflow.read_text(encoding="utf-8").replace(
            f"name: {guard.POLICY_STEP_NAME}",
            "name: Disabled policy placeholder",
        ),
        encoding="utf-8",
    )

    errors = guard.validate_repository(root)

    assert any("exactly one effective sovereignty step" in error for error in errors)


def test_pull_request_path_filter_is_rejected(tmp_path: Path) -> None:
    guard = _load_guard()
    root = _copy_contract(tmp_path, guard)
    workflow = root / ".github" / "workflows" / "policy.yml"
    workflow.write_text(
        workflow.read_text(encoding="utf-8").replace(
            "  pull_request:\n",
            "  pull_request:\n    paths:\n      - '**.py'\n",
        ),
        encoding="utf-8",
    )

    errors = guard.validate_repository(root)

    assert any("must not use path filters" in error for error in errors)


def test_formal_review_cannot_be_changed_to_automatic_approval(tmp_path: Path) -> None:
    guard = _load_guard()
    root = _copy_contract(tmp_path, guard)
    publisher = root / "amosclaud_bot" / "review_publisher.py"
    publisher.write_text(
        publisher.read_text(encoding="utf-8").replace(
            '"event": "COMMENT"',
            '"event": "APPROVE"',
        ),
        encoding="utf-8",
    )

    errors = guard.validate_repository(root)

    assert any("must submit only GitHub COMMENT reviews" in error for error in errors)


def test_formal_review_cannot_execute_pull_request_checkout(tmp_path: Path) -> None:
    guard = _load_guard()
    root = _copy_contract(tmp_path, guard)
    workflow = root / ".github" / "workflows" / "amosclaud-bot-review.yml"
    workflow.write_text(
        workflow.read_text(encoding="utf-8").replace(
            "ref: ${{ github.event.repository.default_branch }}",
            "ref: ${{ github.event.pull_request.head.sha }}",
        ),
        encoding="utf-8",
    )

    errors = guard.validate_repository(root)

    assert any("must check out the trusted default branch" in error for error in errors)


def test_formal_review_cannot_receive_protected_secrets(tmp_path: Path) -> None:
    guard = _load_guard()
    root = _copy_contract(tmp_path, guard)
    workflow = root / ".github" / "workflows" / "amosclaud-bot-review.yml"
    workflow.write_text(
        workflow.read_text(encoding="utf-8").replace(
            "GITHUB_TOKEN: ${{ github.token }}",
            "GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}",
        ),
        encoding="utf-8",
    )

    errors = guard.validate_repository(root)

    assert any("must not use pull_request_target or protected secrets" in error for error in errors)


def test_security_bridge_allowlist_cannot_be_broadened(tmp_path: Path) -> None:
    guard = _load_guard()
    root = _copy_contract(tmp_path, guard)
    workflow = root / ".github" / "workflows" / "amosclaud-security-repair-bridge.yml"
    workflow.write_text(
        workflow.read_text(encoding="utf-8").replace(
            "      - Fortify AST Scan\n",
            "      - Fortify AST Scan\n      - Untrusted Workflow\n",
        ),
        encoding="utf-8",
    )

    errors = guard.validate_repository(root)

    assert any("source allowlist changed" in error for error in errors)


def test_security_bridge_repair_target_cannot_be_replaced(tmp_path: Path) -> None:
    guard = _load_guard()
    root = _copy_contract(tmp_path, guard)
    bridge = root / "amoscloud_ai" / "security_repair_bridge.py"
    bridge.write_text(
        bridge.read_text(encoding="utf-8").replace(
            guard.REPAIR_WORKFLOW,
            "untrusted-fixer.yml",
        ),
        encoding="utf-8",
    )

    errors = guard.validate_repository(root)

    assert any("security bridge repair target changed" in error for error in errors)


def test_dependency_gate_cannot_ignore_low_severity_threats(tmp_path: Path) -> None:
    guard = _load_guard()
    root = _copy_contract(tmp_path, guard)
    workflow = root / ".github" / "workflows" / "amosclaud-dependency-threat-gate.yml"
    workflow.write_text(
        workflow.read_text(encoding="utf-8").replace(
            "fail-on-severity: low",
            "fail-on-severity: high",
        ),
        encoding="utf-8",
    )

    errors = guard.validate_repository(root)

    assert any("dependency threat gate is missing required text" in error for error in errors)


def test_security_connection_code_owner_cannot_be_removed(tmp_path: Path) -> None:
    guard = _load_guard()
    root = _copy_contract(tmp_path, guard)
    codeowners = root / ".github" / "CODEOWNERS"
    protected_line = f"/amoscloud_ai/security_repair_bridge.py {guard.CODE_OWNER}"
    codeowners.write_text(
        codeowners.read_text(encoding="utf-8").replace(protected_line, ""),
        encoding="utf-8",
    )

    errors = guard.validate_repository(root)

    assert any("CODEOWNERS is missing effective protected entry" in error for error in errors)

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


def _replace(path: Path, old: str, new: str, count: int = -1) -> None:
    text = path.read_text(encoding="utf-8")
    updated = text.replace(old, new, count)
    assert updated != text, f"test mutation did not change {path}: {old!r}"
    path.write_text(updated, encoding="utf-8")


def test_repository_policy_contract_is_intact() -> None:
    guard = _load_guard()
    assert guard.validate_repository(ROOT) == []


def test_removing_policy_marker_is_rejected(tmp_path: Path) -> None:
    guard = _load_guard()
    root = _copy_contract(tmp_path, guard)
    _replace(
        root / "docs" / "CONTRIBUTOR_TOOL_POLICY.md",
        guard.POLICY_MARKER,
        "REMOVED",
    )
    assert any(
        "canonical policy is missing required text" in error
        for error in guard.validate_repository(root)
    )


def test_removing_or_commenting_code_owner_is_rejected(tmp_path: Path) -> None:
    guard = _load_guard()
    root = _copy_contract(tmp_path, guard)
    codeowners = root / ".github" / "CODEOWNERS"
    protected = f"/docs/CONTRIBUTOR_TOOL_POLICY.md {guard.CODE_OWNER}"
    _replace(codeowners, f"* {guard.CODE_OWNER}", f"# * {guard.CODE_OWNER}", 1)
    _replace(codeowners, protected, f"# {protected}")
    assert any("CODEOWNERS effective rule" in error for error in guard.validate_repository(root))


def test_later_broad_codeowner_rule_cannot_override_owner(tmp_path: Path) -> None:
    guard = _load_guard()
    root = _copy_contract(tmp_path, guard)
    codeowners = root / ".github" / "CODEOWNERS"
    codeowners.write_text(
        codeowners.read_text(encoding="utf-8") + "\n* @untrusted-contributor\n",
        encoding="utf-8",
    )
    errors = guard.validate_repository(root)
    assert any("CODEOWNERS effective rule" in error for error in errors)


def test_removing_or_commenting_workflow_guard_is_rejected(tmp_path: Path) -> None:
    guard = _load_guard()
    root = _copy_contract(tmp_path, guard)
    workflow = root / ".github" / "workflows" / "policy.yml"
    _replace(workflow, guard.POLICY_COMMAND, f"# {guard.POLICY_COMMAND}")
    assert any("does not execute the policy guard" in error for error in guard.validate_repository(root))


def test_policy_job_cannot_be_disabled_with_condition(tmp_path: Path) -> None:
    guard = _load_guard()
    root = _copy_contract(tmp_path, guard)
    workflow = root / ".github" / "workflows" / "policy.yml"
    _replace(workflow, "  policy:\n", "  policy:\n    if: false\n")
    assert any("job must not be conditional" in error for error in guard.validate_repository(root))


def test_policy_step_cannot_be_disabled_with_condition(tmp_path: Path) -> None:
    guard = _load_guard()
    root = _copy_contract(tmp_path, guard)
    workflow = root / ".github" / "workflows" / "policy.yml"
    _replace(
        workflow,
        f"      - name: {guard.POLICY_STEP_NAME}\n",
        f"      - name: {guard.POLICY_STEP_NAME}\n        if: false\n",
    )
    assert any("step must not be conditional" in error for error in guard.validate_repository(root))


def test_renaming_policy_step_is_rejected(tmp_path: Path) -> None:
    guard = _load_guard()
    root = _copy_contract(tmp_path, guard)
    workflow = root / ".github" / "workflows" / "policy.yml"
    _replace(
        workflow,
        f"name: {guard.POLICY_STEP_NAME}",
        "name: Disabled policy placeholder",
    )
    assert any(
        "exactly one effective sovereignty step" in error
        for error in guard.validate_repository(root)
    )


def test_pull_request_path_filter_is_rejected(tmp_path: Path) -> None:
    guard = _load_guard()
    root = _copy_contract(tmp_path, guard)
    workflow = root / ".github" / "workflows" / "policy.yml"
    _replace(
        workflow,
        "  pull_request:\n",
        "  pull_request:\n    paths:\n      - '**.py'\n",
    )
    assert any("must not use path filters" in error for error in guard.validate_repository(root))


def test_formal_review_cannot_be_changed_to_automatic_approval(tmp_path: Path) -> None:
    guard = _load_guard()
    root = _copy_contract(tmp_path, guard)
    publisher = root / "amosclaud_bot" / "review_publisher.py"
    _replace(publisher, '"event": "COMMENT"', '"event": "APPROVE"')
    assert any(
        "must submit only GitHub COMMENT reviews" in error
        for error in guard.validate_repository(root)
    )


def test_formal_review_cannot_remove_command_filter(tmp_path: Path) -> None:
    guard = _load_guard()
    root = _copy_contract(tmp_path, guard)
    workflow = root / ".github" / "workflows" / "amosclaud-bot-review.yml"
    _replace(workflow, "@amosclaud-bot review", "@disabled-bot review")
    assert any("formal review job filter is missing" in error for error in guard.validate_repository(root))


def test_formal_review_cannot_execute_pull_request_checkout(tmp_path: Path) -> None:
    guard = _load_guard()
    root = _copy_contract(tmp_path, guard)
    workflow = root / ".github" / "workflows" / "amosclaud-bot-review.yml"
    _replace(
        workflow,
        "ref: ${{ github.event.repository.default_branch }}",
        "ref: ${{ github.event.pull_request.head.sha }}",
    )
    assert any(
        "must check out the trusted default branch" in error
        for error in guard.validate_repository(root)
    )


def test_formal_review_cannot_receive_protected_secrets(tmp_path: Path) -> None:
    guard = _load_guard()
    root = _copy_contract(tmp_path, guard)
    workflow = root / ".github" / "workflows" / "amosclaud-bot-review.yml"
    _replace(
        workflow,
        "GITHUB_TOKEN: ${{ github.token }}",
        "GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}",
    )
    assert any(
        "must not use pull_request_target or protected secrets" in error
        for error in guard.validate_repository(root)
    )


def test_review_cannot_restore_unqualified_approval(tmp_path: Path) -> None:
    guard = _load_guard()
    root = _copy_contract(tmp_path, guard)
    publisher = root / "amosclaud_bot" / "review_publisher.py"
    _replace(
        publisher,
        'base = base.replace("**APPROVE**", "**NEEDS HUMAN REVIEW**")',
        "# approval conversion removed",
    )
    assert any(
        "truthful coverage rule" in error for error in guard.validate_repository(root)
    )


def test_status_contract_cannot_remove_required_workflow_set(tmp_path: Path) -> None:
    guard = _load_guard()
    root = _copy_contract(tmp_path, guard)
    status_board = root / "amosclaud_bot" / "status_board.py"
    _replace(status_board, "_REQUIRED_PULL_REQUEST_WORKFLOWS", "_OPTIONAL_WORKFLOWS")
    assert any("status board is missing" in error for error in guard.validate_repository(root))


def test_default_bot_slug_cannot_drift(tmp_path: Path) -> None:
    guard = _load_guard()
    root = _copy_contract(tmp_path, guard)
    profile = root / "amoscloud_ai" / "bot_contributor_profile.py"
    _replace(profile, 'DEFAULT_APP_SLUG = "amosclaud-bot"', 'DEFAULT_APP_SLUG = "other-app"')
    assert any("default App slug" in error for error in guard.validate_repository(root))


def test_security_bridge_allowlist_cannot_be_broadened(tmp_path: Path) -> None:
    guard = _load_guard()
    root = _copy_contract(tmp_path, guard)
    workflow = root / ".github" / "workflows" / "amosclaud-security-repair-bridge.yml"
    _replace(
        workflow,
        "      - Fortify AST Scan\n",
        "      - Fortify AST Scan\n      - Untrusted Workflow\n",
    )
    assert any("source allowlist changed" in error for error in guard.validate_repository(root))


def test_security_bridge_repair_target_cannot_be_replaced(tmp_path: Path) -> None:
    guard = _load_guard()
    root = _copy_contract(tmp_path, guard)
    bridge = root / "amoscloud_ai" / "security_repair_bridge.py"
    _replace(bridge, guard.REPAIR_WORKFLOW, "untrusted-fixer.yml")
    assert any("security bridge repair target changed" in error for error in guard.validate_repository(root))


def test_trusted_codeql_gate_cannot_checkout_pull_request_code(tmp_path: Path) -> None:
    guard = _load_guard()
    root = _copy_contract(tmp_path, guard)
    workflow = root / ".github" / "workflows" / "amosclaud-codeql-threat-gate.yml"
    _replace(
        workflow,
        "ref: ${{ github.event.repository.default_branch }}",
        "ref: ${{ github.event.pull_request.head.sha }}",
    )
    errors = guard.validate_repository(root)
    assert any("trusted CodeQL gate" in error for error in errors)


def test_trusted_codeql_gate_cannot_execute_pr_script(tmp_path: Path) -> None:
    guard = _load_guard()
    root = _copy_contract(tmp_path, guard)
    workflow = root / ".github" / "workflows" / "amosclaud-codeql-threat-gate.yml"
    _replace(
        workflow,
        guard.CODEQL_GATE_COMMAND,
        "python scripts/ci/advanced_security_gate.py",
    )
    assert any("trusted alert evaluator" in error for error in guard.validate_repository(root))


def test_dependency_gate_cannot_ignore_low_severity_threats(tmp_path: Path) -> None:
    guard = _load_guard()
    root = _copy_contract(tmp_path, guard)
    workflow = root / ".github" / "workflows" / "amosclaud-dependency-threat-gate.yml"
    _replace(workflow, "fail-on-severity: low", "fail-on-severity: high")
    assert any(
        "dependency threat gate is missing" in error
        for error in guard.validate_repository(root)
    )


def test_differential_ast_gate_cannot_stop_scanning_exact_base(tmp_path: Path) -> None:
    guard = _load_guard()
    root = _copy_contract(tmp_path, guard)
    workflow = root / ".github" / "workflows" / "fortify.yml"
    _replace(
        workflow,
        "github.event.pull_request.base.sha",
        "github.event.pull_request.head.sha",
    )
    assert any("AST threat gate is missing" in error for error in guard.validate_repository(root))


def test_differential_ast_gate_cannot_remove_comparator(tmp_path: Path) -> None:
    guard = _load_guard()
    root = _copy_contract(tmp_path, guard)
    workflow = root / ".github" / "workflows" / "fortify.yml"
    _replace(workflow, "python head/scripts/ci/bandit_pr_gate.py", "echo comparator removed")
    assert any("AST threat gate is missing" in error for error in guard.validate_repository(root))


def test_differential_ast_gate_cannot_add_suppression_flags(tmp_path: Path) -> None:
    guard = _load_guard()
    root = _copy_contract(tmp_path, guard)
    workflow = root / ".github" / "workflows" / "fortify.yml"
    _replace(
        workflow,
        "python -m bandit -r src amoscloud_ai",
        "python -m bandit -r src amoscloud_ai --skip B602",
        1,
    )
    assert any("forbidden suppression" in error for error in guard.validate_repository(root))

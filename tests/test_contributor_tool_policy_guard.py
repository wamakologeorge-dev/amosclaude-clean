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

    assert any("CODEOWNERS is missing protected entry" in error for error in errors)


def test_removing_workflow_guard_invocation_is_rejected(tmp_path: Path) -> None:
    guard = _load_guard()
    root = _copy_contract(tmp_path, guard)
    workflow = root / ".github" / "workflows" / "policy.yml"
    workflow.write_text(
        workflow.read_text(encoding="utf-8").replace(
            "python scripts/ci/contributor_tool_policy_guard.py",
            "echo policy guard removed",
        ),
        encoding="utf-8",
    )

    errors = guard.validate_repository(root)

    assert any("policy workflow is missing enforcement" in error for error in errors)

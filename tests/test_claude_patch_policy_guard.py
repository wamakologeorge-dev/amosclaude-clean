from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUARD_PATH = ROOT / "scripts" / "ci" / "claude_patch_policy_guard.py"


def load_guard():
    spec = importlib.util.spec_from_file_location("claude_patch_policy_guard", GUARD_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def copy_contract(tmp_path: Path, guard) -> Path:
    root = tmp_path / "repository"
    for relative in guard.PROTECTED_FILES:
        source = ROOT / relative
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    return root


def test_repository_claude_patch_contract_is_intact() -> None:
    guard = load_guard()

    assert guard.validate_repository(ROOT) == []


def test_trusted_checkout_cannot_be_changed_to_pr_head(tmp_path: Path) -> None:
    guard = load_guard()
    root = copy_contract(tmp_path, guard)
    workflow = root / guard.WORKFLOW
    workflow.write_text(
        workflow.read_text(encoding="utf-8").replace(
            "ref: ${{ github.event.repository.default_branch }}",
            "ref: ${{ github.event.pull_request.head.sha }}",
            1,
        ),
        encoding="utf-8",
    )

    errors = guard.validate_repository(root)

    assert any(
        "trusted control plane must check out the default branch" in error for error in errors
    )


def test_force_push_cannot_be_added(tmp_path: Path) -> None:
    guard = load_guard()
    root = copy_contract(tmp_path, guard)
    workflow = root / guard.WORKFLOW
    workflow.write_text(
        workflow.read_text(encoding="utf-8").replace(
            'git -C target push origin "HEAD:refs/heads/${HEAD_REF}"',
            'git -C target push --force origin "HEAD:refs/heads/${HEAD_REF}"',
        ),
        encoding="utf-8",
    )

    errors = guard.validate_repository(root)

    assert any("forbidden authority: --force" in error for error in errors)


def test_executor_cannot_gain_commit_authority(tmp_path: Path) -> None:
    guard = load_guard()
    root = copy_contract(tmp_path, guard)
    executor = root / guard.EXECUTOR
    executor.write_text(
        executor.read_text(encoding="utf-8") + '\nFORBIDDEN = "git commit"\n',
        encoding="utf-8",
    )

    errors = guard.validate_repository(root)

    assert any("forbidden execution authority: git commit" in error for error in errors)


def test_all_fix_commands_cannot_be_silently_routed_to_claude(tmp_path: Path) -> None:
    guard = load_guard()
    root = copy_contract(tmp_path, guard)
    parser = root / guard.PARSER
    parser.write_text(
        parser.read_text(encoding="utf-8").replace(
            'patch_executor = authorized_write and source_format == "claude-patch-alias"',
            "patch_executor = authorized_write",
        ),
        encoding="utf-8",
    )

    errors = guard.validate_repository(root)

    assert any('source_format == "claude-patch-alias"' in error for error in errors)


def test_verification_cannot_receive_anthropic_key(tmp_path: Path) -> None:
    guard = load_guard()
    root = copy_contract(tmp_path, guard)
    workflow = root / guard.WORKFLOW
    workflow.write_text(
        workflow.read_text(encoding="utf-8").replace(
            "env -u ANTHROPIC_API_KEY -u GITHUB_APP_PRIVATE_KEY -u GITHUB_APP_WEBHOOK_SECRET",
            "env",
        ),
        encoding="utf-8",
    )

    errors = guard.validate_repository(root)

    assert any("env -u ANTHROPIC_API_KEY" in error for error in errors)

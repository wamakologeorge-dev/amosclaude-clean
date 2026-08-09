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


def test_repository_ollama_patch_contract_is_intact() -> None:
    guard = load_guard()
    assert guard.validate_repository(ROOT) == []


def test_dispatcher_cannot_restore_anthropic_key(tmp_path: Path) -> None:
    guard = load_guard()
    root = copy_contract(tmp_path, guard)
    workflow = root / guard.DISPATCHER
    workflow.write_text(
        workflow.read_text(encoding="utf-8")
        + "\n# ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}\n",
        encoding="utf-8",
    )
    errors = guard.validate_repository(root)
    assert any("ANTHROPIC_API_KEY" in error for error in errors)


def test_dispatcher_must_use_native_repair_control_plane(tmp_path: Path) -> None:
    guard = load_guard()
    root = copy_contract(tmp_path, guard)
    workflow = root / guard.DISPATCHER
    workflow.write_text(
        workflow.read_text(encoding="utf-8").replace(
            "gh workflow run amosclaud-repair-control-plane.yml",
            "gh workflow run another-worker.yml",
        ),
        encoding="utf-8",
    )
    errors = guard.validate_repository(root)
    assert any("amosclaud-repair-control-plane.yml" in error for error in errors)


def test_worker_cannot_gain_push_authority(tmp_path: Path) -> None:
    guard = load_guard()
    root = copy_contract(tmp_path, guard)
    workflow = root / guard.WORKER
    workflow.write_text(
        workflow.read_text(encoding="utf-8") + '\n# git push origin HEAD:main\n',
        encoding="utf-8",
    )
    errors = guard.validate_repository(root)
    assert any("git push" in error for error in errors)


def test_parser_requires_bounded_ollama_objective(tmp_path: Path) -> None:
    guard = load_guard()
    root = copy_contract(tmp_path, guard)
    parser = root / guard.PARSER
    parser.write_text(
        parser.read_text(encoding="utf-8").replace(
            "and bool(compact_objective)",
            "and True",
        ),
        encoding="utf-8",
    )
    errors = guard.validate_repository(root)
    assert any("bool(compact_objective)" in error for error in errors)


def test_retired_executor_cannot_restore_network_client(tmp_path: Path) -> None:
    guard = load_guard()
    root = copy_contract(tmp_path, guard)
    executor = root / guard.EXECUTOR
    executor.write_text(
        executor.read_text(encoding="utf-8") + "\nimport urllib.request\n",
        encoding="utf-8",
    )
    errors = guard.validate_repository(root)
    assert any("urllib.request" in error for error in errors)

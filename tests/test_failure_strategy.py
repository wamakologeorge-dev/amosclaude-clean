from __future__ import annotations

from pathlib import Path

from amoscloud_ai.repair_engine.failure_strategy import (
    apply_ci_failure_strategy,
    missing_packages,
)


def test_missing_module_evidence_is_allowlisted() -> None:
    evidence = "/usr/bin/python: No module named pytest\nModuleNotFoundError: No module named 'unknown_sdk'"

    assert missing_packages(evidence) == ["pytest"]


def test_real_ci_failure_adds_pytest_to_existing_workflow_install(tmp_path: Path) -> None:
    workflow = tmp_path / ".github" / "workflows" / "ci.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(
        "name: CI\n"
        "on: pull_request\n"
        "jobs:\n"
        "  test:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: python -m pip install -e .\n"
        "      - run: python -m pytest -q\n",
        encoding="utf-8",
    )

    repairs = apply_ci_failure_strategy(tmp_path, "/usr/bin/python: No module named pytest")

    assert any(item.changed for item in repairs)
    updated = workflow.read_text(encoding="utf-8")
    assert "python -m pip install -e . pytest" in updated
    assert "python -m pytest -q" in updated


def test_failure_strategy_does_not_guess_unknown_dependency(tmp_path: Path) -> None:
    workflow = tmp_path / ".github" / "workflows" / "ci.yml"
    workflow.parent.mkdir(parents=True)
    original = (
        "name: CI\n"
        "on: pull_request\n"
        "jobs:\n"
        "  test:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: python -m pip install -e .\n"
        "      - run: python -m mystery_sdk\n"
    )
    workflow.write_text(original, encoding="utf-8")

    repairs = apply_ci_failure_strategy(tmp_path, "No module named 'mystery_sdk'")

    assert repairs == []
    assert workflow.read_text(encoding="utf-8") == original


def test_failure_strategy_does_not_edit_workflow_that_does_not_invoke_module(tmp_path: Path) -> None:
    workflow = tmp_path / ".github" / "workflows" / "build.yml"
    workflow.parent.mkdir(parents=True)
    original = (
        "name: Build\n"
        "on: push\n"
        "jobs:\n"
        "  build:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: python -m pip install -e .\n"
        "      - run: python -m compileall .\n"
    )
    workflow.write_text(original, encoding="utf-8")

    repairs = apply_ci_failure_strategy(tmp_path, "No module named pytest")

    assert repairs == []
    assert workflow.read_text(encoding="utf-8") == original

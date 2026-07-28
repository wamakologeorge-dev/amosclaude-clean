from pathlib import Path

import pytest

from scripts.ci.fast_gate import (
    FastGateError,
    select_fast_tests,
    validate_python,
    validate_yaml,
)


def test_validate_python_accepts_valid_source_and_rejects_syntax(tmp_path: Path) -> None:
    valid = tmp_path / "valid.py"
    valid.write_text("value = 1\n", encoding="utf-8")
    validate_python(valid)

    invalid = tmp_path / "invalid.py"
    invalid.write_text("def broken(:\n", encoding="utf-8")
    with pytest.raises(FastGateError):
        validate_python(invalid)


def test_validate_python_rejects_merge_markers(tmp_path: Path) -> None:
    path = tmp_path / "conflict.py"
    path.write_text(
        "<<<<<<< HEAD\nvalue = 1\n=======\nvalue = 2\n>>>>>>> branch\n",
        encoding="utf-8",
    )
    with pytest.raises(FastGateError):
        validate_python(path)


def test_validate_yaml_accepts_mapping_and_rejects_invalid_yaml(tmp_path: Path) -> None:
    valid = tmp_path / "valid.yml"
    valid.write_text("jobs:\n  test:\n    runs-on: ubuntu-latest\n", encoding="utf-8")
    validate_yaml(valid)

    invalid = tmp_path / "invalid.yml"
    invalid.write_text("jobs: [\n", encoding="utf-8")
    with pytest.raises(FastGateError):
        validate_yaml(invalid)


def test_repository_behavior_changes_select_focused_tests(tmp_path: Path) -> None:
    behavior_test = tmp_path / "tests" / "test_repository_behavior_automation.py"
    fast_test = tmp_path / "tests" / "test_fast_pr_gate.py"
    behavior_test.parent.mkdir(parents=True)
    behavior_test.write_text("", encoding="utf-8")
    fast_test.write_text("", encoding="utf-8")

    selected = select_fast_tests(
        [".github/scripts/repository_behavior.py"],
        root=tmp_path,
    )

    assert selected == (
        "tests/test_fast_pr_gate.py",
        "tests/test_repository_behavior_automation.py",
    )


def test_unrelated_change_runs_only_fast_gate_tests(tmp_path: Path) -> None:
    fast_test = tmp_path / "tests" / "test_fast_pr_gate.py"
    fast_test.parent.mkdir(parents=True)
    fast_test.write_text("", encoding="utf-8")

    assert select_fast_tests(["amoscloud_ai/main.py"], root=tmp_path) == (
        "tests/test_fast_pr_gate.py",
    )

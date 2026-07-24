from __future__ import annotations

import pytest

from amoscloud_ai.runner_client import _execute, _verification_id


def test_runner_verification_id_is_deterministic(tmp_path):
    evidence = ["Doctor: passed", "pytest: 12 passed"]

    first = _verification_id("task_example", tmp_path, evidence)
    second = _verification_id("task_example", tmp_path, evidence)
    changed = _verification_id("task_example", tmp_path, [*evidence, "new check"])

    assert first.startswith("verify_")
    assert len(first) == 39
    assert first == second
    assert first != changed


def test_runner_will_not_claim_unexecuted_tests_as_verified(tmp_path):
    with pytest.raises(RuntimeError, match="No tests directory"):
        _execute(
            {
                "id": "task_missing_tests",
                "mode": "test",
                "objective": "Run the workspace tests",
            },
            tmp_path,
        )

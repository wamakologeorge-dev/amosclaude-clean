from amosclaud_bot.approval_gate import (
    _approval_source,
    _high_risk_files,
    _is_sensitive_objective,
    _normalize_objective,
)


def test_sensitive_fix_objective_detection() -> None:
    assert _is_sensitive_objective("update production deployment workflow")
    assert _is_sensitive_objective("rotate authentication credential handling")
    assert not _is_sensitive_objective("fix typo in README")


def test_high_risk_pull_request_paths() -> None:
    files = [
        {"filename": ".github/workflows/deploy.yml"},
        {"filename": "src/service.py"},
        {"filename": "SECURITY.md"},
    ]
    assert _high_risk_files(files) == [".github/workflows/deploy.yml", "SECURITY.md"]


def test_approval_source_is_bound_to_exact_normalized_objective() -> None:
    first = _approval_source(474, " Production   deployment workflow ")
    same = _approval_source(474, "production deployment workflow")
    different = _approval_source(474, "production authentication workflow")

    assert first == same
    assert first != different
    assert first.startswith("issue-comment-474-")


def test_objective_normalization_is_stable() -> None:
    assert _normalize_objective("  Fix   Production WORKFLOW  ") == "fix production workflow"

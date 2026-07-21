from amosclaud_bot.approval_gate import _high_risk_files, _is_sensitive_objective


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

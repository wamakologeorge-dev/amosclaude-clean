from amosclaud_bot.approvals import _risk_reasons, _tool_requires_approval


def test_sensitive_fixer_request_requires_human_approval():
    requires, matches = _tool_requires_approval("@amosclaud fix production deployment workflow")
    assert requires is True
    assert "production" in matches
    assert "deployment" in matches
    assert "workflow" in matches


def test_normal_targeted_fix_does_not_require_extra_approval():
    requires, matches = _tool_requires_approval("@amosclaud fix failing unit test")
    assert requires is False
    assert matches == []


def test_high_risk_pull_request_paths_generate_approval_reasons():
    reasons = _risk_reasons(
        [
            {
                "filename": ".github/workflows/deploy.yml",
                "additions": 5,
                "deletions": 2,
            },
            {
                "filename": "src/auth/permissions.py",
                "additions": 3,
                "deletions": 1,
            },
        ]
    )
    assert any("High-risk" in reason for reason in reasons)
    assert any("Security/authentication-sensitive" in reason for reason in reasons)


def test_low_risk_pull_request_does_not_generate_approval_reasons():
    reasons = _risk_reasons(
        [
            {
                "filename": "docs/usage.md",
                "additions": 10,
                "deletions": 0,
            }
        ]
    )
    assert reasons == []

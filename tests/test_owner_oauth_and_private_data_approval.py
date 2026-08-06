from pathlib import Path

from amosclaud_bot import approval_gate
from amoscloud_ai.api.routes import owner_bootstrap

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_owner_oauth_uses_registered_callback_by_default(monkeypatch) -> None:
    source = read("amoscloud_ai/api/routes/owner_bootstrap.py")

    monkeypatch.delenv("GITHUB_ADMIN_SEND_REDIRECT_URI", raising=False)
    assert not owner_bootstrap._send_github_redirect_uri()

    monkeypatch.setenv("GITHUB_ADMIN_SEND_REDIRECT_URI", "true")
    assert owner_bootstrap._send_github_redirect_uri()
    assert 'authorize_parameters["redirect_uri"] = callback' in source
    assert 'token_parameters["redirect_uri"] = callback' in source


def test_owner_cookies_work_across_www_and_apex_domains() -> None:
    owner = read("amoscloud_ai/api/routes/owner_bootstrap.py")
    auth = read("amoscloud_ai/api/routes/auth.py")

    assert "domain=_shared_cookie_domain()" in owner
    assert "domain=_cookie_domain()" in auth


def test_github_owner_cannot_be_converted_by_password_recovery() -> None:
    recovery = read("amoscloud_ai/api/routes/account_recovery.py")

    assert 'user["provider"] != "github-admin"' in recovery
    assert 'user["provider"] == "github-admin"' in recovery
    assert "This platform-owner account is GitHub-only" in recovery


def test_normal_code_and_workflow_repairs_do_not_need_approval() -> None:
    files = [
        {"filename": ".github/workflows/ci.yml", "patch": "+ model secret reference"},
        {"filename": "amoscloud_ai/api/routes/auth.py", "patch": "+ login repair"},
    ]

    assert approval_gate._high_risk_files(files) == []
    assert not approval_gate._is_sensitive_objective(
        "fix the authentication workflow and permissions"
    )


def test_private_information_changes_still_need_approval() -> None:
    files = [
        {"filename": ".env", "patch": "- removed private value"},
        {"filename": "private.pem", "patch": "- removed credential material"},
    ]

    assert len(approval_gate._high_risk_files(files)) == 2
    assert approval_gate._is_sensitive_objective(
        "remove a leaked key from repository history"
    )

from pathlib import Path

from amoscloud_ai.main import create_app


ROOT = Path(__file__).resolve().parents[1]


def _paths() -> set[str]:
    return {getattr(route, "path", "") for route in create_app().routes}


def test_account_recovery_routes_are_registered() -> None:
    paths = _paths()
    required = {
        "/api/v1/auth/account-recovery/email/request",
        "/api/v1/auth/account-recovery/email/verify",
        "/api/v1/auth/account-recovery/username/request",
        "/api/v1/auth/account-recovery/username/verify",
        "/api/v1/auth/account-recovery/password/request",
        "/api/v1/auth/account-recovery/password/reset",
    }
    assert not (required - paths)


def test_login_page_exposes_complete_account_access() -> None:
    html = (ROOT / "web" / "login.html").read_text(encoding="utf-8")
    for text in (
        "Create account",
        "Forgot password",
        "Forgot username",
        "Recovery email",
        "no-reply@amosclaud.com",
        "/static/account-access.js",
    ):
        assert text in html
    assert "login-recovery.js" not in html
    assert "/static/login.js" not in html


def test_account_access_uses_visible_recovery_flows() -> None:
    script = (ROOT / "web" / "account-access.js").read_text(encoding="utf-8")
    assert "window.prompt" not in script
    assert "/api/v1/auth/account-recovery/username/request" in script
    assert "/api/v1/auth/account-recovery/username/verify" in script
    assert "/api/v1/auth/account-recovery/password/request" in script
    assert "/api/v1/auth/account-recovery/password/reset" in script
    assert "/api/v1/auth/account-recovery/email/request" in script
    assert "/api/v1/auth/account-recovery/email/verify" in script


def test_security_mail_sender_is_amosclaud_owned() -> None:
    source = (ROOT / "amoscloud_ai" / "mail_delivery.py").read_text(encoding="utf-8")
    assert "no-reply@amosclaud.com" in source
    assert 'endswith("@amosclaud.com")' in source
    assert "smtp.login" in source
    assert "print(" not in source


def test_password_recovery_revokes_existing_sessions() -> None:
    source = (ROOT / "amoscloud_ai" / "api" / "routes" / "account_recovery.py").read_text(encoding="utf-8")
    assert "DELETE FROM sessions WHERE user_id=?" in source
    assert "MAX_ATTEMPTS" in source
    assert "Invalid or expired verification code" in source

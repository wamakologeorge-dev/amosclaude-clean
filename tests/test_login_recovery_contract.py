from pathlib import Path


def test_login_recovery_prevents_duplicate_account_creation():
    script = Path("web/login-recovery.js").read_text(encoding="utf-8")
    assert "start.response.status === 409" in script
    assert "Amosclaud will not create another account" in script
    assert "/api/v1/auth/password/forgot" in script
    assert "/api/v1/auth/password/reset" in script
    assert "window.location.replace('/cloud/agent')" in script


def test_auth_rate_limit_uses_new_shorter_namespace():
    source = Path("amoscloud_ai/security.py").read_text(encoding="utf-8")
    assert 'AUTH_RATE_WINDOW_SECONDS", "300"' in source
    assert 'AUTH_RATE_MAX_ATTEMPTS", "30"' in source
    assert 'AUTH_RATE_NAMESPACE", "v2"' in source
    assert "self.auth_rate_namespace" in source

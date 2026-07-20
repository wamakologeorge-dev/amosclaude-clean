from pathlib import Path

from amoscloud_ai.api.routes.auth import _cookie_secure
from amoscloud_ai.main import create_app


def route_paths() -> set[str]:
    return {getattr(route, "path", "") for route in create_app().routes}


def test_http_deployment_does_not_force_secure_cookie(monkeypatch):
    monkeypatch.delenv("AUTH_COOKIE_SECURE", raising=False)
    monkeypatch.setenv("AMOSCLAUD_PUBLIC_URL", "http://www.amosclaud.com/")
    assert _cookie_secure() is False


def test_https_deployment_enables_secure_cookie(monkeypatch):
    monkeypatch.delenv("AUTH_COOKIE_SECURE", raising=False)
    monkeypatch.setenv("AMOSCLAUD_PUBLIC_URL", "https://www.amosclaud.com/")
    assert _cookie_secure() is True


def test_profile_routes_are_registered():
    paths = route_paths()
    assert "/api/v1/profile/me" in paths


def test_login_page_handles_insecure_passkey_context():
    script = Path("web/login.js").read_text(encoding="utf-8")
    assert "window.isSecureContext" in script
    assert "Passkey sign-in requires HTTPS" in script
    assert "credentials: 'same-origin'" in script


def test_standalone_shell_and_requirements_exist():
    assert Path("scripts/amosclaud-shell").is_file()
    assert Path("amoscloud_ai/solo_shell.py").is_file()
    assert Path(".amosclaud/platform-requirements.json").is_file()
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    assert 'amosclaud-shell = "amoscloud_ai.solo_shell:main"' in pyproject

from pathlib import Path

from amoscloud_ai import admin_bootstrap

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_configured_repository_owner_is_the_default_root_identity(monkeypatch) -> None:
    for name in (
        "AMOSCLAUD_ADMIN_GITHUB_IDS",
        "AMOSCLAUD_ADMIN_GITHUB_LOGINS",
        "AMOSCLAUD_ADMIN_GITHUB_REPOSITORY",
        "AMOSCLAUD_ADMIN_GITHUB_EMAIL",
    ):
        monkeypatch.delenv(name, raising=False)

    assert admin_bootstrap.is_configured_github_admin(
        "271083488",
        "wamakologeorge-dev",
    )
    assert (
        admin_bootstrap.configured_admin_github_repository()
        == "wamakologeorge-dev/amosclaude-clean"
    )
    assert admin_bootstrap.configured_admin_github_email() == "wamakologeorge@gmail.com"


def test_unknown_github_identity_never_receives_root_access() -> None:
    assert not admin_bootstrap.is_configured_github_admin(
        "999999999",
        "wamakologeorge-dev",
    )
    assert not admin_bootstrap.is_configured_github_admin(
        "271083488",
        "lookalike-owner",
    )


def test_owner_login_requires_github_oauth_and_repository_control() -> None:
    owner_auth = _read("amoscloud_ai/api/routes/owner_bootstrap.py")

    assert '@router.get("/github/admin-login"' in owner_auth
    assert '@router.get("/github/admin-callback"' in owner_auth
    assert "https://github.com/login/oauth/authorize" in owner_auth
    assert "https://github.com/login/oauth/access_token" in owner_auth
    assert "https://api.github.com/user" in owner_auth
    assert 'f"https://api.github.com/repos/{repository_name}"' in owner_auth
    assert 'permissions.get("admin") is True' in owner_auth
    assert 'str(owner.get("login") or "").lower() == login.lower()' in owner_auth
    assert "is_configured_github_admin" in owner_auth


def test_verified_owner_becomes_passwordless_root_and_old_sessions_end() -> None:
    owner_auth = _read("amoscloud_ai/api/routes/owner_bootstrap.py")

    assert "password_hash=NULL" in owner_auth
    assert "provider='github-admin',is_admin=1" in owner_auth
    assert 'db.execute("DELETE FROM sessions WHERE user_id=?"' in owner_auth
    assert 'RedirectResponse("/admin?github=owner"' in owner_auth
    assert "auth._set_session_cookie(response, token)" in owner_auth


def test_github_owner_cannot_use_password_email_code_or_reset_paths() -> None:
    owner_auth = _read("amoscloud_ai/api/routes/owner_bootstrap.py")

    assert 'user["provider"] == "github-admin"' in owner_auth
    assert "This platform-owner account is GitHub-only" in owner_auth
    assert '@router.post("/login", response_model=auth.UserResponse)' in owner_auth
    assert '@router.post("/login/verify-code"' in owner_auth
    assert '@router.post("/password/reset"' in owner_auth


def test_login_page_exposes_one_clear_github_owner_action() -> None:
    login = _read("web/login.html")

    assert "GitHub-verified root access" in login
    assert "Continue with GitHub as wamakologeorge-dev" in login
    assert 'href="/api/v1/auth/github/admin-login"' in login
    assert "No Amosclaud username, email code, or platform password" in login


def test_production_example_documents_exact_oauth_callback() -> None:
    example = _read(".env.production.example")

    assert (
        "GITHUB_ADMIN_CALLBACK_URL=https://www.amosclaud.com/" "api/v1/auth/github/admin-callback"
    ) in example
    assert "AMOSCLAUD_ADMIN_GITHUB_IDS=271083488" in example
    assert "AMOSCLAUD_ADMIN_GITHUB_LOGINS=wamakologeorge-dev" in example
    assert ("AMOSCLAUD_ADMIN_GITHUB_REPOSITORY=" "wamakologeorge-dev/amosclaude-clean") in example

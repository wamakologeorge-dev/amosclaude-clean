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


def test_owner_recovery_route_requires_exact_configured_identity() -> None:
    owner_auth = _read("amoscloud_ai/api/routes/owner_bootstrap.py")

    assert '@router.get("/github/admin-login"' in owner_auth
    assert '@router.get("/github/admin-callback"' in owner_auth
    assert "https://github.com/login/oauth/authorize" in owner_auth
    assert "https://github.com/login/oauth/access_token" in owner_auth
    assert "https://api.github.com/user" in owner_auth
    assert "is_configured_github_admin" in owner_auth
    assert 'permissions.get("admin") is True' not in owner_auth
    assert "GitHub App authorization and installation are separate" in owner_auth


def test_public_github_signup_accepts_any_identity_but_never_grants_admin() -> None:
    public_auth = _read("amoscloud_ai/api/routes/github_access_gateway.py")

    assert '"allow_signup": "true"' in public_auth
    assert "_find_or_create_github_user" in public_auth
    assert "VALUES (?,?,NULL,?,'github',0,?)" in public_auth
    assert "should_grant_admin" not in public_auth
    assert "is_configured_github_admin" not in public_auth


def test_email_password_and_code_access_remain_primary() -> None:
    auth = _read("amoscloud_ai/api/routes/auth.py")
    public_auth = _read("amoscloud_ai/api/routes/github_access_gateway.py")
    login = _read("web/login.html")

    for route in (
        '@router.post("/login"',
        '@router.post("/login/request-code"',
        '@router.post("/login/verify-code"',
        '@router.post("/register/request-code"',
        '@router.post("/register/verify"',
        '@router.post("/password/forgot"',
        '@router.post("/password/reset"',
    ):
        assert route in auth

    assert '"optional": True' in public_auth
    assert "status_code=410" not in public_auth
    assert "github_account_required" not in public_auth
    assert "location.replace('/auth/github')" not in login
    assert "<form" in login
    assert 'type="password"' in login
    assert "/static/account-access.js" in login
    assert "Create account" in login
    assert "Email me a sign-in code" in login
    assert "Forgot password?" in login


def test_owner_callback_still_issues_an_admin_session() -> None:
    owner_auth = _read("amoscloud_ai/api/routes/owner_bootstrap.py")

    assert 'RedirectResponse("/admin?github=owner"' in owner_auth
    assert "auth._set_session_cookie(response, token)" in owner_auth
    assert 'db.execute("DELETE FROM sessions WHERE user_id=?"' in owner_auth


def test_production_example_documents_public_and_unified_callbacks() -> None:
    example = _read(".env.production.example")
    canonical = "https://www.amosclaud.com/api/v1/auth/github/admin-callback"

    assert "GITHUB_CALLBACK_URL=https://www.amosclaud.com/auth/github/callback" in example
    assert f"GITHUB_ADMIN_CALLBACK_URL={canonical}" in example
    assert f"GITHUB_REPOSITORY_CALLBACK_URL={canonical}" in example
    assert "AMOSCLAUD_ADMIN_GITHUB_IDS=271083488" in example
    assert "AMOSCLAUD_ADMIN_GITHUB_LOGINS=wamakologeorge-dev" in example
    assert ("AMOSCLAUD_ADMIN_GITHUB_REPOSITORY=" "wamakologeorge-dev/amosclaude-clean") in example

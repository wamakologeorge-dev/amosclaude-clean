from pathlib import Path

from fastapi import Response

from amoscloud_ai import admin_bootstrap
from amoscloud_ai.api.routes import auth

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


def test_optional_owner_github_route_requires_exact_configured_identity() -> None:
    owner_auth = _read("amoscloud_ai/api/routes/owner_bootstrap.py")

    assert '@router.get("/github/admin-login"' in owner_auth
    assert '@router.get("/github/admin-callback"' in owner_auth
    assert "https://github.com/login/oauth/authorize" in owner_auth
    assert "https://github.com/login/oauth/access_token" in owner_auth
    assert "https://api.github.com/user" in owner_auth
    assert "is_configured_github_admin" in owner_auth

    # GitHub authorization remains an optional recovery path. It must not require
    # the App installation before the configured owner can prove identity.
    assert 'f"https://api.github.com/repos/{repository_name}"' not in owner_auth
    assert 'permissions.get("admin") is True' not in owner_auth
    assert "GitHub App authorization and installation are separate" in owner_auth


def test_optional_github_verification_preserves_email_access() -> None:
    owner_auth = _read("amoscloud_ai/api/routes/owner_bootstrap.py")

    assert "password_hash=NULL" not in owner_auth
    assert (
        'provider = "password+github-admin" if user["password_hash"] else "github-admin"'
        in owner_auth
    )
    assert "preserve any existing password so email access continues to work" in owner_auth
    assert 'db.execute("DELETE FROM sessions WHERE user_id=?"' in owner_auth
    assert 'RedirectResponse("/admin?github=owner"' in owner_auth
    assert "auth._set_session_cookie(response, token)" in owner_auth


def test_existing_github_owner_can_use_email_code_and_password_reset(
    monkeypatch,
    tmp_path,
) -> None:
    auth.DB_PATH = tmp_path / "owner-email-access.db"
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "false")
    delivered: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        auth,
        "_send_code",
        lambda email, code, purpose: delivered.append((email, code, purpose)),
    )

    owner_email = "wamakologeorge@gmail.com"
    with auth._connect() as db:
        db.execute(
            """INSERT INTO users(
                   name,email,password_hash,github_id,provider,is_admin,created_at
               ) VALUES (?,?,NULL,?,'github-admin',1,?)""",
            (
                "wamakologeorge-dev",
                owner_email,
                "271083488",
                "2026-08-06T00:00:00+00:00",
            ),
        )
        db.commit()

    auth.request_login_code(auth.EmailRequest(email=owner_email))
    login_code = delivered[-1]
    assert login_code[0] == owner_email
    assert login_code[2] == "login"

    code_response = Response()
    code_user = auth.verify_login_code(
        auth.EmailCodeLoginRequest(email=owner_email, code=login_code[1]),
        code_response,
    )
    assert code_user.is_admin is True
    assert "amos_session=" in code_response.headers["set-cookie"]

    auth.forgot_password(auth.EmailRequest(email=owner_email))
    reset_code = delivered[-1]
    assert reset_code[2] == "reset"
    auth.reset_password(
        auth.PasswordResetRequest(
            email=owner_email,
            password="new-owner-password-123",
            code=reset_code[1],
        )
    )

    password_response = Response()
    password_user = auth.login(
        auth.LoginRequest(
            email=owner_email,
            password="new-owner-password-123",
        ),
        password_response,
    )
    assert password_user.is_admin is True
    assert password_user.provider == "password"
    assert "amos_session=" in password_response.headers["set-cookie"]


def test_primary_account_routes_use_one_standard_authentication_system() -> None:
    main = _read("amoscloud_ai/main.py")
    owner_auth = _read("amoscloud_ai/api/routes/owner_bootstrap.py")
    script = _read("web/account-access.js")

    assert "app.include_router(auth.router, include_in_schema=False)" in main
    assert "return auth.login(body, response)" in owner_auth
    assert "return auth.request_login_code(body)" in owner_auth
    assert "return auth.verify_login_code(body, response)" in owner_auth
    assert "return auth.forgot_password(body)" in owner_auth
    assert "return auth.reset_password(body)" in owner_auth

    for route in (
        "/auth/login",
        "/auth/login/request-code",
        "/auth/login/verify-code",
        "/auth/register/request-code",
        "/auth/register/verify",
        "/auth/password/forgot",
        "/auth/password/reset",
    ):
        assert route in script
    assert "/api/v1/auth/login/request-code" not in script
    assert "/api/v1/auth/password/forgot" not in script


def test_login_page_exposes_one_professional_account_flow() -> None:
    login = _read("web/login.html")

    assert "Welcome to Amosclaud" in login
    assert "Create account" in login
    assert "Email me a sign-in code" in login
    assert "Forgot password?" in login
    assert "secure code on any device" in login
    assert "Organization ID" not in login
    assert "GitHub-verified root access" not in login
    assert "Continue with GitHub" not in login
    assert "/static/unified-login.js" not in login
    assert "/static/account-access.js" in login


def test_production_example_documents_exact_oauth_callback() -> None:
    example = _read(".env.production.example")

    assert (
        "GITHUB_ADMIN_CALLBACK_URL=https://www.amosclaud.com/" "api/v1/auth/github/admin-callback"
    ) in example
    assert "AMOSCLAUD_ADMIN_GITHUB_IDS=271083488" in example
    assert "AMOSCLAUD_ADMIN_GITHUB_LOGINS=wamakologeorge-dev" in example
    assert ("AMOSCLAUD_ADMIN_GITHUB_REPOSITORY=" "wamakologeorge-dev/amosclaude-clean") in example

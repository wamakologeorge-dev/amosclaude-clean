from pathlib import Path

from amoscloud_ai.api.routes import github_access_gateway

ROOT = Path(__file__).resolve().parents[1]


def test_public_account_entry_is_github_only() -> None:
    source = (ROOT / "amoscloud_ai/api/routes/github_access_gateway.py").read_text(
        encoding="utf-8"
    )

    assert '@router.get("/login"' in source
    assert '@router.get("/signup"' in source
    assert '@router.get("/create-account"' in source
    assert 'RedirectResponse("/auth/github"' in source
    assert '"allow_signup": "true"' in source
    assert 'GITHUB_SCOPE = "read:user user:email repo"' in source


def test_login_page_has_no_email_password_or_recovery_form() -> None:
    html = (ROOT / "web/login.html").read_text(encoding="utf-8")

    assert "location.replace('/auth/github')" in html
    assert "Continue with GitHub" in html
    assert "<form" not in html
    assert "type=\"password\"" not in html
    assert "Forgot password" not in html
    assert "Create account" not in html
    assert "/static/account-access.js" not in html


def test_old_account_endpoints_are_blocked_by_production_gateway() -> None:
    paths = {
        route.path
        for route in github_access_gateway.router.routes
        if hasattr(route, "path") and "POST" in getattr(route, "methods", set())
    }

    assert {
        "/auth/login",
        "/auth/login/request-code",
        "/auth/login/verify-code",
        "/auth/register/request-code",
        "/auth/register/verify",
        "/auth/password/forgot",
        "/auth/password/reset",
    }.issubset(paths)


def test_github_callback_creates_or_signs_in_account() -> None:
    source = (ROOT / "amoscloud_ai/api/routes/github_access_gateway.py").read_text(
        encoding="utf-8"
    )

    assert '@router.get("/auth/github/callback"' in source
    assert "_find_or_create_github_user" in source
    assert "password_hash,github_id,provider" in source
    assert "VALUES (?,?,NULL,?,'github',?,?)" in source
    assert "auth._set_session_cookie(response, token)" in source


def test_only_verified_github_email_can_link_existing_account() -> None:
    source = (ROOT / "amoscloud_ai/api/routes/github_access_gateway.py").read_text(
        encoding="utf-8"
    )

    assert "item.get(\"verified\")" in source
    assert "if not user and verified_email" in source
    assert "users.noreply.amosclaud.local" in source


def test_combined_production_app_registers_github_gateway_before_platform() -> None:
    source = (ROOT / "amoscloud_ai/combined_app.py").read_text(encoding="utf-8")

    github_route = source.index("app.include_router(github_access_gateway.router)")
    platform_mount = source.index('app.mount("/", HostedToolSupportASGI(platform_app)')
    assert github_route < platform_mount
    assert "app.include_router(github_access_gateway.router, prefix=\"/api/v1\")" in source

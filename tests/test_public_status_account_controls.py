from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_public_status_is_read_only_and_available_without_login() -> None:
    health = _read("amoscloud_ai/api/routes/health.py")
    page = _read("web/status.html")
    script = _read("web/status.js")

    assert '@router.get("/status", include_in_schema=False)' in health
    assert '@router.get("/api/v1/public/status"' in health
    assert (
        "get_user_from_session"
        not in health.split('@router.get("/status", include_in_schema=False)', 1)[1].split(
            '@router.get("/account", include_in_schema=False)', 1
        )[0]
    )
    assert "/api/v1/public/status" in script
    assert "credentials: 'omit'" in script
    assert "private repositories, keys, task logs" in page


def test_account_page_requires_session_and_exposes_self_service_controls() -> None:
    health = _read("amoscloud_ai/api/routes/health.py")
    account = _read("amoscloud_ai/api/routes/account.py")
    page = _read("web/account.html")
    script = _read("web/account-settings.js")
    command_center = _read("web/command-center.html")

    assert '@router.get("/account", include_in_schema=False)' in health
    assert 'RedirectResponse("/login", status_code=302)' in health
    assert '@router.post("/logout-all"' in account
    assert '@router.post("/share-session"' in account
    assert "shared_token = _create_session" in account
    assert "_token_hash(amos_session)" in account
    assert 'response.delete_cookie(SESSION_COOKIE, path="/")' in account
    assert '@router.delete("", status_code=204)' in account
    assert "Sign out all devices" in page
    assert "Delete account permanently" in page
    assert 'href="/account">Account</a>' in command_center
    assert "/api/v1/account/logout-all" in script
    assert "method: 'DELETE'" in script


def test_login_exposes_username_password_and_trusted_qr() -> None:
    login = _read("web/login.html")
    github_access = _read("amoscloud_ai/api/routes/github_access_gateway.py")

    assert "<form" in login
    assert 'type="password"' in login
    assert "/static/login.js" in login
    assert "Username" in login
    assert "Sign in with password" in login
    assert "Scan secure QR code" in login
    assert "Create account" in login
    assert "Email me a sign-in code" not in login
    assert "Continue with Google" not in login
    assert "location.replace('/auth/github')" not in login
    assert '@router.get("/auth/github"' in github_access
    assert '@router.get("/auth/github/callback"' in github_access
    assert '"optional": True' in github_access
    assert "auth._set_session_cookie(response, token)" in github_access
    assert "_find_or_create_github_user" in github_access

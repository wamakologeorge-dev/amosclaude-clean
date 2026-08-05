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

    assert '@router.get("/account", include_in_schema=False)' in health
    assert 'RedirectResponse("/login", status_code=302)' in health
    assert '@router.post("/logout-all"' in account
    assert '@router.post("/share-session"' in account
    assert '@router.delete("", status_code=204)' in account
    assert "Sign out all devices" in page
    assert "Delete account permanently" in page
    assert "/api/v1/account/logout-all" in script
    assert "method: 'DELETE'" in script


def test_login_offers_public_status_and_promotes_new_sessions() -> None:
    login = _read("web/login.html")
    bridge = _read("web/session-cookie-bridge.js")

    assert 'href="/status"' in login
    assert "/static/session-cookie-bridge.js" in login
    assert "/api/v1/auth/login" in bridge
    assert "/api/v1/auth/register/verify" in bridge
    assert "/api/v1/account/share-session" in bridge

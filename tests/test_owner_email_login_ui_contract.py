from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_password_login_accepts_username_or_existing_email() -> None:
    login_html = _read("web/login.html")
    login_js = _read("web/login.js")

    assert "Username or owner email" in login_html
    assert "yourname or owner@gmail.com" in login_html
    assert "function accountAddress(value)" in login_js
    assert "normalized.includes('@') ? normalized" in login_js
    assert "email: accountAddress(loginUsername.value)" in login_js


def test_qr_login_remains_username_bound() -> None:
    login_js = _read("web/login.js")

    assert "function qrUsername(value)" in login_js
    assert "QR sign-in requires your Amosclaud username" in login_js
    assert "username: requestedUsername" in login_js

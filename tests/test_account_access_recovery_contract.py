from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException, Response
from starlette.requests import Request

from amoscloud_ai.api.routes import auth, passkey_signup
from amoscloud_ai.main import create_app

ROOT = Path(__file__).resolve().parents[1]


def _request(path: str = "/api/v1/auth/login/qr/start") -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "https",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [(b"host", b"www.amosclaud.com")],
            "client": ("127.0.0.1", 1234),
            "server": ("www.amosclaud.com", 443),
            "root_path": "",
        }
    )


def _paths() -> set[str]:
    return {getattr(route, "path", "") for route in create_app().routes}


def test_username_password_and_qr_routes_are_registered() -> None:
    required = {
        "/auth/login",
        "/api/v1/auth/register/passkey/start",
        "/api/v1/auth/register/passkey/finish",
        "/api/v1/auth/login/qr/start",
        "/api/v1/auth/login/qr/image",
        "/api/v1/auth/login/qr/device",
        "/api/v1/auth/login/qr/device/start",
        "/api/v1/auth/login/qr/device/finish",
        "/api/v1/auth/login/qr/verify",
    }
    assert not (required - _paths())


def test_login_page_uses_username_password_and_trusted_qr_only() -> None:
    html = (ROOT / "web/login.html").read_text(encoding="utf-8")

    for text in (
        "Username",
        "Sign in with password",
        "Scan secure QR code",
        "Six-digit code from your trusted device",
        "Create account",
        "/static/login.js",
    ):
        assert text in html

    for removed in (
        "Continue with Google",
        "Sign up with Google",
        "Sign in directly as platform owner",
        "Email me a sign-in code",
        "/static/account-access.js",
    ):
        assert removed not in html


def test_login_script_binds_qr_and_password_to_the_username() -> None:
    script = (ROOT / "web/login.js").read_text(encoding="utf-8")

    assert "`${username(value)}@amosclaud.com`" in script
    assert "/api/v1/auth/login/qr/start" in script
    assert "/api/v1/auth/login/qr/verify" in script
    assert "/api/v1/auth/login" in script
    assert "browser_token: qrBrowserToken" in script
    assert "window.isSecureContext" in script


def test_existing_username_is_rejected_before_account_creation(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(auth, "DB_PATH", tmp_path / "duplicate.db")
    with auth._connect() as db:
        passkey_signup._prepare(db)
        cursor = db.execute(
            """INSERT INTO users(name,email,password_hash,provider,is_admin,created_at)
               VALUES (?,?,?,?,0,?)""",
            (
                "Existing User",
                "george@amosclaud.com",
                auth._hash_password("correct-horse-battery-staple"),
                "passkey",
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        db.execute(
            "INSERT INTO mailboxes(user_id,username,address,created_at) VALUES (?,?,?,?)",
            (
                cursor.lastrowid,
                "george",
                "george@amosclaud.com",
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        db.commit()

    with pytest.raises(HTTPException) as error:
        passkey_signup.start_passkey_signup(
            passkey_signup.PasskeyStartRequest(
                name="Another User",
                username="George",
                password="another-secure-password",
            )
        )

    assert error.value.status_code == 409
    assert "already taken" in str(error.value.detail)


def test_pending_username_reservation_prevents_parallel_creation(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(auth, "DB_PATH", tmp_path / "pending.db")
    now = datetime.now(timezone.utc)
    with auth._connect() as db:
        passkey_signup._prepare(db)
        db.execute(
            """INSERT INTO passkey_signups(
                   username,name,address,password_hash,user_handle,challenge,expires_at,created_at
               ) VALUES (?,?,?,?,?,?,?,?)""",
            (
                "reserved",
                "First Request",
                "reserved@amosclaud.com",
                auth._hash_password("first-secure-password"),
                b"user-handle",
                b"challenge",
                (now + timedelta(minutes=10)).isoformat(),
                now.isoformat(),
            ),
        )
        db.commit()

    with pytest.raises(HTTPException) as error:
        passkey_signup.start_passkey_signup(
            passkey_signup.PasskeyStartRequest(
                name="Second Request",
                username="reserved",
                password="second-secure-password",
            )
        )

    assert error.value.status_code == 409


def test_qr_challenge_is_opaque_and_bound_to_one_username(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(auth, "DB_PATH", tmp_path / "qr.db")
    monkeypatch.setenv("AMOSCLAUD_PUBLIC_URL", "https://www.amosclaud.com")
    now = datetime.now(timezone.utc).isoformat()
    with auth._connect() as db:
        passkey_signup._prepare_qr(db)
        cursor = db.execute(
            """INSERT INTO users(name,email,password_hash,provider,is_admin,created_at)
               VALUES (?,?,?,?,0,?)""",
            (
                "QR User",
                "qruser@amosclaud.com",
                auth._hash_password("secure-password-123"),
                "passkey",
                now,
            ),
        )
        db.execute(
            "INSERT INTO mailboxes(user_id,username,address,created_at) VALUES (?,?,?,?)",
            (cursor.lastrowid, "qruser", "qruser@amosclaud.com", now),
        )
        db.commit()

    result = passkey_signup.start_qr_login(
        passkey_signup.QRLoginStartRequest(username="QRUser"),
        _request(),
    )

    assert "qruser" not in str(result["challenge"]).lower()
    assert result["challenge"] != result["browser_token"]
    assert str(result["qr_image_url"]).startswith("/api/v1/auth/login/qr/image")
    with auth._connect() as db:
        row = db.execute("SELECT username,user_id FROM qr_login_challenges").fetchone()
    assert row["username"] == "qruser"
    assert row["user_id"] is not None


def test_qr_code_creates_one_session_and_cannot_be_reused(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(auth, "DB_PATH", tmp_path / "qr-once.db")
    now = datetime.now(timezone.utc)
    challenge = "challenge-token-that-is-long-enough"
    browser_token = "browser-token-that-is-long-enough"
    code = "314159"
    with auth._connect() as db:
        passkey_signup._prepare_qr(db)
        cursor = db.execute(
            """INSERT INTO users(name,email,password_hash,provider,is_admin,created_at)
               VALUES (?,?,?,?,0,?)""",
            (
                "One Time User",
                "onetime@amosclaud.com",
                auth._hash_password("secure-password-123"),
                "passkey",
                now.isoformat(),
            ),
        )
        db.execute(
            """INSERT INTO qr_login_challenges(
                   challenge_hash,username,user_id,browser_token_hash,code_hash,
                   code_expires_at,approved_at,expires_at,created_at
               ) VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                auth._token_hash(challenge),
                "onetime",
                cursor.lastrowid,
                auth._token_hash(browser_token),
                auth._token_hash(code),
                (now + timedelta(minutes=5)).isoformat(),
                now.isoformat(),
                (now + timedelta(minutes=2)).isoformat(),
                now.isoformat(),
            ),
        )
        db.commit()

    response = Response()
    result = passkey_signup.verify_qr_login(
        passkey_signup.QRLoginVerifyRequest(
            username="onetime",
            challenge=challenge,
            browser_token=browser_token,
            code=code,
        ),
        response,
    )
    assert result["user"]["email"] == "onetime@amosclaud.com"
    assert "amos_session=" in response.headers["set-cookie"]

    with pytest.raises(HTTPException) as reused:
        passkey_signup.verify_qr_login(
            passkey_signup.QRLoginVerifyRequest(
                username="onetime",
                challenge=challenge,
                browser_token=browser_token,
                code=code,
            ),
            Response(),
        )
    assert reused.value.status_code == 400

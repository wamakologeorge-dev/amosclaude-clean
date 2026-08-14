"""Tests for self-service password changes."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import httpx

from amoscloud_ai.api.routes import auth
from amoscloud_ai.main import create_app


async def _request(app, method: str, path: str, **kwargs):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.request(method, path, **kwargs)


def request(app, method: str, path: str, **kwargs):
    return asyncio.run(_request(app, method, path, **kwargs))


def _create_password_user(email: str, password: str) -> str:
    with auth._connect() as db:
        cursor = db.execute(
            "INSERT INTO users(name,email,password_hash,provider,is_admin,created_at) VALUES (?,?,?,'password',0,?)",
            (
                "Password Test",
                email,
                auth._hash_password(password),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        token = auth._create_session(db, int(cursor.lastrowid))
    return token


def _create_github_only_user(email: str) -> str:
    with auth._connect() as db:
        cursor = db.execute(
            "INSERT INTO users(name,email,password_hash,github_id,provider,is_admin,created_at) "
            "VALUES (?,?,NULL,?,'github',0,?)",
            ("GitHub Only", email, "gh-12345", datetime.now(timezone.utc).isoformat()),
        )
        token = auth._create_session(db, int(cursor.lastrowid))
    return token


def test_change_password_succeeds_with_correct_current_password(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "DB_PATH", tmp_path / "auth.db")
    app = create_app()
    token = _create_password_user("change-ok@example.com", "correct-password-1")

    response = request(
        app,
        "POST",
        "/api/v1/account/password",
        cookies={"amos_session": token},
        json={"current_password": "correct-password-1", "new_password": "new-password-2"},
    )

    assert response.status_code == 204

    login = request(
        app,
        "POST",
        "/api/v1/auth/login",
        json={"email": "change-ok@example.com", "password": "new-password-2"},
    )
    assert login.status_code == 200

    old_login = request(
        app,
        "POST",
        "/api/v1/auth/login",
        json={"email": "change-ok@example.com", "password": "correct-password-1"},
    )
    assert old_login.status_code == 401


def test_change_password_rejects_wrong_current_password(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "DB_PATH", tmp_path / "auth.db")
    app = create_app()
    token = _create_password_user("wrong-current@example.com", "correct-password-1")

    response = request(
        app,
        "POST",
        "/api/v1/account/password",
        cookies={"amos_session": token},
        json={"current_password": "totally-wrong", "new_password": "new-password-2"},
    )

    assert response.status_code == 403
    with auth._connect() as db:
        user = db.execute(
            "SELECT password_hash FROM users WHERE email=?", ("wrong-current@example.com",)
        ).fetchone()
    assert auth._verify_password("correct-password-1", user["password_hash"])


def test_change_password_requires_current_password_when_set(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "DB_PATH", tmp_path / "auth.db")
    app = create_app()
    token = _create_password_user("missing-current@example.com", "correct-password-1")

    response = request(
        app,
        "POST",
        "/api/v1/account/password",
        cookies={"amos_session": token},
        json={"new_password": "new-password-2"},
    )

    assert response.status_code == 403


def test_change_password_rejects_too_short_new_password(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "DB_PATH", tmp_path / "auth.db")
    app = create_app()
    token = _create_password_user("too-short@example.com", "correct-password-1")

    response = request(
        app,
        "POST",
        "/api/v1/account/password",
        cookies={"amos_session": token},
        json={"current_password": "correct-password-1", "new_password": "short"},
    )

    assert response.status_code == 422


def test_change_password_rejects_reusing_current_password(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "DB_PATH", tmp_path / "auth.db")
    app = create_app()
    token = _create_password_user("reuse@example.com", "correct-password-1")

    response = request(
        app,
        "POST",
        "/api/v1/account/password",
        cookies={"amos_session": token},
        json={"current_password": "correct-password-1", "new_password": "correct-password-1"},
    )

    assert response.status_code == 400


def test_initial_password_allowed_for_github_only_account(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "DB_PATH", tmp_path / "auth.db")
    app = create_app()
    token = _create_github_only_user("github-only@example.com")

    response = request(
        app,
        "POST",
        "/api/v1/account/password",
        cookies={"amos_session": token},
        json={"new_password": "first-password-1"},
    )

    assert response.status_code == 204

    login = request(
        app,
        "POST",
        "/api/v1/auth/login",
        json={"email": "github-only@example.com", "password": "first-password-1"},
    )
    assert login.status_code == 200

    with auth._connect() as db:
        user = db.execute(
            "SELECT provider FROM users WHERE email=?", ("github-only@example.com",)
        ).fetchone()
    assert user["provider"] == "password+github"


def test_change_password_requires_authentication(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "DB_PATH", tmp_path / "auth.db")
    app = create_app()

    response = request(
        app,
        "POST",
        "/api/v1/account/password",
        json={"current_password": "x", "new_password": "new-password-2"},
    )

    assert response.status_code == 401

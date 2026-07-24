"""Tests for self-service account deletion."""

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


def _create_user(email: str, password: str) -> str:
    with auth._connect() as db:
        cursor = db.execute(
            "INSERT INTO users(name,email,password_hash,provider,is_admin,created_at) VALUES (?,?,?,'password',0,?)",
            ("Delete Test", email, auth._hash_password(password), datetime.now(timezone.utc).isoformat()),
        )
        token = auth._create_session(db, int(cursor.lastrowid))
    return token


def test_delete_account_requires_correct_password(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "DB_PATH", tmp_path / "auth.db")
    app = create_app()
    token = _create_user("delete-wrong@example.com", "correct-password")

    response = request(
        app,
        "DELETE",
        "/api/v1/account",
        cookies={"amos_session": token},
        json={"confirmation": "delete-wrong@example.com", "password": "wrong-password"},
    )

    assert response.status_code == 401
    with auth._connect() as db:
        assert db.execute("SELECT 1 FROM users WHERE email=?", ("delete-wrong@example.com",)).fetchone()


def test_delete_account_removes_user_and_sessions(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "DB_PATH", tmp_path / "auth.db")
    app = create_app()
    token = _create_user("delete-me@example.com", "correct-password")

    response = request(
        app,
        "DELETE",
        "/api/v1/account",
        cookies={"amos_session": token},
        json={"confirmation": "delete-me@example.com", "password": "correct-password"},
    )

    assert response.status_code == 204
    with auth._connect() as db:
        assert db.execute("SELECT 1 FROM users WHERE email=?", ("delete-me@example.com",)).fetchone() is None
        assert db.execute("SELECT 1 FROM sessions").fetchone() is None

    me = request(app, "GET", "/api/v1/auth/me", cookies={"amos_session": token})
    assert me.status_code == 401

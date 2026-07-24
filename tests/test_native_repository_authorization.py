"""Authorization regression tests for native repository development routes."""

import asyncio
from datetime import datetime, timedelta, timezone

import httpx

from amoscloud_ai.api.routes import auth, repositories
from amoscloud_ai.main import create_app


def _create_user_and_session(email: str) -> tuple[str, object]:
    token = f"session-{email}"
    now = datetime.now(timezone.utc)
    with auth._connect() as db:
        cursor = db.execute(
            "INSERT INTO users(name,email,password_hash,provider,is_admin,created_at) VALUES (?,?,?,'password',0,?)",
            (email.split("@", 1)[0], email, auth._hash_password("strong-password"), now.isoformat()),
        )
        user_id = cursor.lastrowid
        db.execute(
            "INSERT INTO sessions(token_hash,user_id,expires_at,created_at) VALUES (?,?,?,?)",
            (
                auth._token_hash(token),
                user_id,
                (now + timedelta(hours=1)).isoformat(),
                now.isoformat(),
            ),
        )
        db.commit()
        user = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    return token, user


def test_public_repository_issue_creation_requires_write_access(tmp_path, monkeypatch):
    database = tmp_path / "auth.db"
    monkeypatch.setattr(auth, "DB_PATH", database)
    monkeypatch.setattr(repositories, "DB_PATH", database)
    monkeypatch.setattr(repositories, "REPOSITORY_ROOT", tmp_path / "repositories")

    _, owner = _create_user_and_session("owner@example.com")
    outsider_token, _ = _create_user_and_session("outsider@example.com")
    repository = repositories.create_repository(
        repositories.RepositoryCreate(name="public-project", visibility="public"), owner
    )

    async def create_issue_as_outsider() -> httpx.Response:
        transport = httpx.ASGITransport(app=create_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            client.cookies.set(auth.SESSION_COOKIE, outsider_token)
            return await client.post(
                f"/api/v1/repositories/{repository.id}/issues",
                json={"title": "Unauthorized issue"},
            )

    response = asyncio.run(create_issue_as_outsider())

    assert response.status_code == 403
    assert response.json()["detail"] == "Write access required"

    with repositories._db() as db:
        issue_count = db.execute(
            "SELECT COUNT(*) FROM native_issues WHERE repository_id=?", (repository.id,)
        ).fetchone()[0]
    assert issue_count == 0

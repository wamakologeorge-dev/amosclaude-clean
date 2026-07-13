from datetime import datetime, timedelta, timezone

import asyncio
import secrets

import httpx

from amoscloud_ai.api.routes import auth, repositories
from amoscloud_ai.main import create_app


def test_authenticated_chat_creates_repository(tmp_path, monkeypatch):
    database = tmp_path / "auth.db"
    repository_root = tmp_path / "repositories"
    monkeypatch.setattr(auth, "DB_PATH", database)
    monkeypatch.setattr(repositories, "DB_PATH", database)
    monkeypatch.setattr(repositories, "REPOSITORY_ROOT", repository_root)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    with auth._connect() as db:
        cursor = db.execute(
            "INSERT INTO users(name,email,password_hash,provider,is_admin,created_at) VALUES (?,?,?,'password',0,?)",
            ("Developer", "developer@example.com", auth._hash_password("strong-password"), now.isoformat()),
        )
        db.execute(
            "INSERT INTO sessions(token_hash,user_id,expires_at,created_at) VALUES (?,?,?,?)",
            (
                auth._token_hash(token),
                cursor.lastrowid,
                (now + timedelta(hours=1)).isoformat(),
                now.isoformat(),
            ),
        )
        db.commit()

    app = create_app()

    async def send():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            client.cookies.set(auth.SESSION_COOKIE, token)
            return await client.post(
                "/api/chat",
                json={"message": "Create a public repository for Amosclaud"},
            )

    response = asyncio.run(send())
    assert response.status_code == 200
    assert response.headers.get("content-type", "").startswith("application/json")
    body = response.json()
    assert body["provider"] == "amosclaud"
    assert body["task_status"] == "completed"
    assert body["task_url"].startswith("/workspace/")

    repository_id = int(body["task_id"])
    path = repository_root / str(repository_id)
    assert (path / ".git").is_dir()
    assert (path / "README.md").is_file()

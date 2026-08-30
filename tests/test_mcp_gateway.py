"""Contracts for the first-party Amosclaud MCP repository gateway."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from amoscloud_ai.api.routes import auth, mcp_gateway, repositories


def _app_with_user(tmp_path: Path, monkeypatch, *, scopes=None) -> TestClient:
    db_path = tmp_path / "auth.db"
    repository_root = tmp_path / "repositories"
    monkeypatch.setattr(auth, "DB_PATH", db_path)
    monkeypatch.setattr(repositories, "DB_PATH", db_path)
    monkeypatch.setattr(repositories, "REPOSITORY_ROOT", repository_root)

    with auth._connect() as db:
        db.execute(
            """INSERT INTO users(name,email,password_hash,provider,is_admin,created_at,email_verified)
               VALUES (?,?,?,?,?,?,?)""",
            (
                "MCP Developer",
                "mcp@example.com",
                None,
                "password",
                0,
                datetime.now(timezone.utc).isoformat(),
                1,
            ),
        )
        db.commit()

    identity = {
        "user_id": 1,
        "is_admin": False,
        "key_type": "amosclaud-authority",
    }
    if scopes is not None:
        identity["scopes"] = list(scopes)

    monkeypatch.setattr(
        mcp_gateway,
        "bearer_identity",
        lambda token: identity if token == "test-amos-token" else None,
    )

    app = FastAPI()
    app.include_router(mcp_gateway.router, prefix="/api/v1")
    return TestClient(app)


def _headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-amos-token"}


def test_gateway_proves_amosclaud_identity(tmp_path: Path, monkeypatch) -> None:
    client = _app_with_user(
        tmp_path,
        monkeypatch,
        scopes={"repository:read", "repository:write"},
    )

    response = client.get("/api/v1/mcp-gateway/identity", headers=_headers())

    assert response.status_code == 200
    assert response.json() == {
        "connected": True,
        "provider": "amosclaud",
        "user_id": 1,
        "name": "MCP Developer",
        "email": "mcp@example.com",
        "administrator": False,
        "credential_type": "amosclaud-authority",
        "scopes": ["repository:read", "repository:write"],
    }


def test_gateway_can_create_read_branch_and_commit_native_repository(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client = _app_with_user(
        tmp_path,
        monkeypatch,
        scopes={"repository:read", "repository:write"},
    )

    created = client.post(
        "/api/v1/mcp-gateway/repositories",
        headers=_headers(),
        json={
            "name": "direct-amosclaud",
            "description": "No provider credentials exposed to the MCP client.",
            "visibility": "private",
            "initialize_readme": True,
        },
    )
    assert created.status_code == 201
    repository_id = created.json()["id"]

    write = client.put(
        f"/api/v1/mcp-gateway/repositories/{repository_id}/files",
        headers=_headers(),
        json={
            "path": "hello.txt",
            "content": "hello from Amosclaud MCP\n",
            "branch": "main",
            "commit_message": "Add MCP proof file",
        },
    )
    assert write.status_code == 200
    assert len(write.json()["commit"]) == 40

    read = client.get(
        f"/api/v1/mcp-gateway/repositories/{repository_id}/files",
        headers=_headers(),
        params={"path": "hello.txt", "branch": "main"},
    )
    assert read.status_code == 200
    assert read.json()["content"] == "hello from Amosclaud MCP\n"

    branch = client.post(
        f"/api/v1/mcp-gateway/repositories/{repository_id}/branches",
        headers=_headers(),
        json={"name": "mcp/change", "source_branch": "main"},
    )
    assert branch.status_code == 201
    assert branch.json() == {"name": "mcp/change", "source_branch": "main"}

    branches = client.get(
        f"/api/v1/mcp-gateway/repositories/{repository_id}/branches",
        headers=_headers(),
    )
    assert branches.status_code == 200
    assert set(branches.json()) == {"main", "mcp/change"}

    commits = client.get(
        f"/api/v1/mcp-gateway/repositories/{repository_id}/commits",
        headers=_headers(),
        params={"branch": "main", "limit": 10},
    )
    assert commits.status_code == 200
    assert commits.json()[0]["message"] == "Add MCP proof file"


def test_scoped_read_credential_cannot_write_repository(tmp_path: Path, monkeypatch) -> None:
    client = _app_with_user(tmp_path, monkeypatch, scopes={"repository:read"})

    response = client.post(
        "/api/v1/mcp-gateway/repositories",
        headers=_headers(),
        json={"name": "must-not-exist"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Amosclaud credential requires repository:write"


def test_gateway_rejects_missing_or_invalid_bearer(tmp_path: Path, monkeypatch) -> None:
    client = _app_with_user(tmp_path, monkeypatch, scopes={"repository:read"})

    missing = client.get("/api/v1/mcp-gateway/identity")
    invalid = client.get(
        "/api/v1/mcp-gateway/identity",
        headers={"Authorization": "Bearer wrong"},
    )

    assert missing.status_code == 401
    assert invalid.status_code == 401

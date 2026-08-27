import hashlib
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from amoscloud_ai.api.routes import amosclaud_authority as authority_routes
from amoscloud_ai.api.routes import auth
from amoscloud_ai.main import create_app


def _user(user_id: int = 1, *, is_admin: int = 0) -> dict:
    return {
        "id": user_id,
        "name": "Workspace Owner",
        "email": f"owner{user_id}@example.com",
        "is_admin": is_admin,
        "provider": "password",
    }


def _prepare_database(path, *, workspace_id: str = "ws_authority") -> None:
    auth.DB_PATH = path
    with auth._connect() as db:
        db.execute(
            """INSERT INTO users(id,name,email,password_hash,provider,is_admin,created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (
                1,
                "Workspace Owner",
                "owner@example.com",
                "test",
                "password",
                0,
                "2026-01-01T00:00:00+00:00",
            ),
        )
        db.execute(
            """CREATE TABLE workspaces (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'stopped'
            )"""
        )
        db.execute(
            "INSERT INTO workspaces(id,user_id,status) VALUES (?,?,?)",
            (workspace_id, 1, "stopped"),
        )
        db.commit()


def _client(path, *, user: dict | None = None):
    _prepare_database(path)
    app = create_app()
    app.dependency_overrides[authority_routes._current_user] = lambda: user or _user()
    return TestClient(app)


def test_manifest_declares_first_party_and_external_lifetime_policies(tmp_path):
    client = _client(tmp_path / "manifest.db")
    response = client.get("/api/v1/amosclaud/authority/manifest")

    assert response.status_code == 200
    body = response.json()
    assert body["credential_types"]["api_key"]["expiration"] == "manual_revocation"
    assert body["credential_types"]["token"]["expiration"] == "manual_revocation"
    assert body["credential_types"]["action"]["expiration"] == "manual_revocation"
    assert body["third_party_grants"]["minimum_expiry_days"] == 90
    assert body["integrations"]["github_actions"].startswith("external integration")
    assert body["integrations"]["ollama"].startswith("external model integration")


def test_action_tool_catalog_is_allowlisted_and_scope_bound(tmp_path):
    client = _client(tmp_path / "action-tools.db")
    tools = client.get("/api/v1/amosclaud/authority/action/tools")

    assert tools.status_code == 200
    names = {item["name"] for item in tools.json()["tools"]}
    assert {
        "workspace.start",
        "repository.write",
 "ci.run",
        "github.pull_request.create",
        "deployment.run",
        "model.invoke",
        "action.verify",
    } <= names
    assert all(item["required_scope"] for item in tools.json()["tools"])

    created = client.post(
        "/api/v1/amosclaud/authority/credentials",
        json={
            "name": "Action tool test",
            "type": "action",
            "scopes": ["action:run", "model:invoke"],
        },
    )
    raw = created.json()["secret"]
    allowed = client.get(
        "/api/v1/amosclaud/authority/action/authorize?tool=model.invoke",
        headers={"Authorization": f"Bearer {raw}"},
    )
    assert allowed.status_code == 200
    assert allowed.json()["tool"]["required_scope"] == "model:invoke"

    denied = client.get(
        "/api/v1/amosclaud/authority/action/authorize?tool=deployment.run",
        headers={"Authorization": f"Bearer {raw}"},
    )
    assert denied.status_code == 403

    unknown = client.get(
        "/api/v1/amosclaud/authority/action/authorize?tool=exec.shell",
        headers={"Authorization": f"Bearer {raw}"},
    )
    assert unknown.status_code == 404


def test_platform_credentials_share_verifier_and_never_expire(tmp_path):
    client = _client(tmp_path / "credentials.db")
    scopes = ["action:run", "model:invoke", "workspace:read"]

    created = client.post(
        "/api/v1/amosclaud/authority/credentials",
        json={"name": "Desktop gateway", "type": "action", "scopes": scopes},
    )
    assert created.status_code == 201
    body = created.json()
    raw = body["secret"]
    assert raw.startswith("amos_action_")
    assert body["expires_at"] is None
    assert body["expiration_policy"] == "manual_revocation"

    with auth._connect() as db:
        row = db.execute(
            "SELECT secret_hash,expires_at FROM amosclaud_credentials WHERE id=?",
            (body["id"],),
        ).fetchone()
    assert row["secret_hash"].startswith("pbkdf2_sha256$")
    assert row["secret_hash"] != hashlib.sha256(raw.encode()).hexdigest()
    assert row["expires_at"] is None

    verified = client.get(
        "/api/v1/amosclaud/authority/verify?required_scope=model:invoke",
        headers={"Authorization": f"Bearer {raw}"},
    )
    assert verified.status_code == 200
    assert verified.json()["credential_type"] == "action"
    assert verified.json()["scope_granted"] is True

    denied = client.get(
        "/api/v1/amosclaud/authority/verify?required_scope=github:write",
        headers={"X-API-Key": raw},
    )
    assert denied.status_code == 403

    rotated = client.post(
        f"/api/v1/amosclaud/authority/credentials/{body['id']}/rotate"
    )
    assert rotated.status_code == 201
    replacement = rotated.json()["secret"]
    assert replacement != raw
    assert client.get(
        "/api/v1/amosclaud/authority/verify",
        headers={"Authorization": f"Bearer {raw}"},
    ).status_code == 401
    assert client.get(
        "/api/v1/amosclaud/authority/verify",
        headers={"Authorization": f"Bearer {replacement}"},
    ).status_code == 200

    assert client.delete(
        f"/api/v1/amosclaud/authority/credentials/{rotated.json()['id']}"
    ).status_code == 204
    assert client.get(
        "/api/v1/amosclaud/authority/verify",
        headers={"Authorization": f"Bearer {replacement}"},
    ).status_code == 401


def test_third_party_grants_require_workspace_owner_and_expire(tmp_path):
    client = _client(tmp_path / "grants.db")
    too_short = client.post(
        "/api/v1/amosclaud/authority/workspaces/ws_authority/third-party-grants",
        json={
            "provider": "github",
            "subject": "desktop",
            "scopes": ["github:read"],
            "expires_in_days": 30,
        },
    )
    assert too_short.status_code == 422

    created = client.post(
        "/api/v1/amosclaud/authority/workspaces/ws_authority/third-party-grants",
        json={
            "provider": "github",
            "subject": "desktop",
            "scopes": ["github:read", "pull-requests:create"],
            "expires_in_days": 90,
        },
    )
    assert created.status_code == 201
    body = created.json()
    raw = body["secret"]
    assert raw.startswith("amos_ext_")
    assert body["expires_at"]
    assert body["status"] == "active"

    listing = client.get(
        "/api/v1/amosclaud/authority/workspaces/ws_authority/third-party-grants"
    )
    assert listing.status_code == 200
    assert "secret" not in listing.json()["grants"][0]

    verified = client.get(
        "/api/v1/amosclaud/authority/verify"
        "?required_scope=github:read&workspace_id=ws_authority",
        headers={"Authorization": f"Bearer {raw}"},
    )
    assert verified.status_code == 200
    assert verified.json()["principal_type"] == "third_party_workspace_grant"
    assert verified.json()["workspace_id"] == "ws_authority"

    wrong_workspace = client.get(
        "/api/v1/amosclaud/authority/verify?workspace_id=another-workspace",
        headers={"Authorization": f"Bearer {raw}"},
    )
    assert wrong_workspace.status_code == 401

    with auth._connect() as db:
        row = db.execute(
            "SELECT expires_at FROM amosclaud_workspace_grants WHERE id=?",
            (body["id"],),
        ).fetchone()
    expiry = datetime.fromisoformat(row["expires_at"])
    assert expiry > datetime.now(timezone.utc) + timedelta(days=89)


def test_third_party_grant_cannot_be_managed_by_another_workspace_owner(tmp_path):
    client = _client(tmp_path / "ownership.db", user=_user(2))
    response = client.get(
        "/api/v1/amosclaud/authority/workspaces/ws_authority/third-party-grants"
    )
    assert response.status_code == 403

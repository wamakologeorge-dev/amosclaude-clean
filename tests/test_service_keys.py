import hashlib

from fastapi.testclient import TestClient

from amoscloud_ai.api.routes import auth, service_keys
from amoscloud_ai.main import create_app


def _admin():
    return {"id": 7, "name": "Owner", "is_admin": 1}


def test_service_key_full_lifecycle_is_real_and_hash_only(tmp_path):
    auth.DB_PATH = tmp_path / "service-keys.db"
    app = create_app()
    app.dependency_overrides[service_keys._admin_user] = _admin
    client = TestClient(app)

    initial = client.get("/api/v1/admin/service-keys/status")
    assert initial.status_code == 200
    assert initial.json()["active_keys"] == 0
    created = client.post(
        "/api/v1/admin/service-keys",
        json={
            "name": "Production Runner",
            "service": "bundle-runner",
            "scopes": ["status:read", "bundles:write"],
        },
    )
    assert created.status_code == 201
    raw = created.json()["key"]
    key_id = created.json()["id"]
    assert raw.startswith("amos_svc_")
    with service_keys._db() as db:
        row = db.execute("SELECT key_hash FROM service_api_keys WHERE id=?", (key_id,)).fetchone()
    assert row["key_hash"] == hashlib.sha256(raw.encode()).hexdigest()
    assert raw not in row["key_hash"]

    listing = client.get("/api/v1/admin/service-keys").json()["data"]
    assert "key" not in listing[0]
    verified = client.get(
        "/api/v1/service-keys/verify?scope=bundles:write",
        headers={"Authorization": f"Bearer {raw}"},
    )
    assert verified.status_code == 200
    assert verified.json()["authenticated"] is True
    assert verified.json()["last_used_at"]
    denied = client.get(
        "/api/v1/service-keys/verify?scope=model:invoke",
        headers={"X-API-Key": raw},
    )
    assert denied.status_code == 403

    rotated = client.post(f"/api/v1/admin/service-keys/{key_id}/rotate")
    replacement = rotated.json()["key"]
    assert replacement != raw
    assert client.get(
        "/api/v1/service-keys/verify", headers={"X-API-Key": raw}
    ).status_code == 401
    assert client.get(
        "/api/v1/service-keys/verify", headers={"X-API-Key": replacement}
    ).status_code == 200
    replacement_id = rotated.json()["id"]
    assert client.delete(f"/api/v1/admin/service-keys/{replacement_id}").status_code == 204
    assert client.get(
        "/api/v1/service-keys/verify", headers={"X-API-Key": replacement}
    ).status_code == 401


def test_control_panel_contains_no_service_key_literal():
    page = open("web/service-key-control-panel.html", encoding="utf-8").read()
    assert "Server service keys" in page
    assert "amos_svc_" not in page
    assert "localStorage" not in page

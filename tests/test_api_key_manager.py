"""End-to-end contract tests for the standalone API-key manager."""
import os
from pathlib import Path

from fastapi.testclient import TestClient


DB_PATH = "/tmp/amosclaud-api-key-manager-test.db"
Path(DB_PATH).unlink(missing_ok=True)
os.environ["API_KEY_DATABASE_URL"] = f"sqlite:///{DB_PATH}"
os.environ["AGENT_JWT_SECRET_KEY"] = "test-secret-key-that-is-longer-than-thirty-two-characters"
os.environ["API_KEY_MANAGER_ADMIN_USERNAME"] = "platform-owner"
os.environ["API_KEY_MANAGER_ADMIN_PASSWORD"] = "correct-horse-battery-staple"

from api_key_manager import main  # noqa: E402


def test_api_key_manager_full_lifecycle():
    with TestClient(main.app) as client:
        assert client.get("/health").json() == {"status": "ok", "service": "api-key-manager"}
        assert client.get("/api-keys/").status_code == 401

        token_response = client.post(
            "/token",
            data={"username": "platform-owner", "password": "correct-horse-battery-staple"},
        )
        assert token_response.status_code == 200
        token = token_response.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        created = client.post("/api-keys/", headers=headers, json={"description": "CI deployment"})
        assert created.status_code == 201
        key = created.json()
        assert key["plain_key"].startswith("ak_")
        assert key["key_prefix"] == key["plain_key"][:11]

        assert client.post("/api-keys/validate", json={"api_key": key["plain_key"]}).json()["is_valid"] is True
        assert client.post("/api-keys/validate", json={"api_key": "wrong"}).json()["is_valid"] is False
        assert client.delete(f"/api-keys/{key['id']}", headers=headers).json()["is_active"] is False
        assert client.post("/api-keys/validate", json={"api_key": key["plain_key"]}).json()["is_valid"] is False

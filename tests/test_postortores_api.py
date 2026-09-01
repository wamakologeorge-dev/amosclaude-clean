from fastapi.testclient import TestClient

from postortores.api import create_app


def _client(monkeypatch, tmp_path, principal: str) -> TestClient:
    token = "abc123"
    monkeypatch.setenv("AMOSCLAUD_POSTORTORES_PATH", str(tmp_path / "api.db"))
    monkeypatch.setenv("AMOSCLAUD_POSTORTORES_TOKEN", token)
    headers = {"Authorization": "Bearer " + token, "X-Amosclaud-Principal": principal}
    return TestClient(create_app(), headers=headers)


def test_postortores_api_requires_service_token_and_principal(monkeypatch, tmp_path):
    token = "abc123"
    monkeypatch.setenv("AMOSCLAUD_POSTORTORES_PATH", str(tmp_path / "api.db"))
    monkeypatch.setenv("AMOSCLAUD_POSTORTORES_TOKEN", token)

    client = TestClient(create_app())
    response = client.post(
        "/v1/state",
        json={"namespace": "workspace", "key": "project", "value": {"name": "alpha"}},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Amosclaud Postortores bearer token required"

    response = client.post(
        "/v1/state",
        json={"namespace": "workspace", "key": "project", "value": {"name": "alpha"}},
        headers={"Authorization": "Bearer " + token},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "X-Amosclaud-Principal is required"


def test_postortores_api_scopes_state_by_principal(monkeypatch, tmp_path):
    alice = _client(monkeypatch, tmp_path, "alice")
    bob = _client(monkeypatch, tmp_path, "bob")

    response = alice.post(
        "/v1/state",
        json={"namespace": "workspace", "key": "project", "value": {"name": "alpha"}, "tags": ["live"]},
    )
    assert response.status_code == 201

    response = alice.get("/v1/state/workspace/project")
    assert response.status_code == 200
    assert response.json()["value"] == {"name": "alpha"}

    response = bob.get("/v1/state/workspace/project")
    assert response.status_code == 404
    assert response.json()["detail"] == "Postortores record not found"


def test_postortores_api_rejects_invalid_evidence_status(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path, "alice")

    response = client.post(
        "/v1/evidence",
        json={
            "subject": "task:7",
            "claim": "tests completed",
            "status": "invalid-status",
            "proof": {"passed": 12},
        },
    )
    assert response.status_code == 422

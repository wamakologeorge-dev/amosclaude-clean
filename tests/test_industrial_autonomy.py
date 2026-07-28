from fastapi.testclient import TestClient

from amoscloud_ai.api.routes import industrial_autonomy
from amoscloud_ai.main import create_app


def _headers() -> dict[str, str]:
    return {"X-Amosclaud-Owner-Key": "owner-secret"}


def _register_asset(client: TestClient) -> str:
    response = client.post(
        "/api/v1/sentinel-grid/assets",
        headers=_headers(),
        json={
            "name": "Plant Inspection Robot 1",
            "asset_type": "robot",
            "site": "test-site",
            "capabilities": ["thermal-camera", "gas-sensor"],
        },
    )
    assert response.status_code == 201
    return response.json()["asset_id"]


def test_sentinel_grid_status_exposes_safe_operating_pipeline() -> None:
    industrial_autonomy.control_plane.reset()

    with TestClient(create_app()) as client:
        response = client.get("/api/v1/sentinel-grid")

    assert response.status_code == 200
    body = response.json()
    assert body["program"] == "Amosclaud SentinelGrid"
    assert body["workflow"] == [
        "observe",
        "diagnose",
        "simulate",
        "recommend",
        "approve",
        "dispatch",
        "verify",
    ]
    assert body["physical_execution"] == "disabled_without_external_approved_adapter"


def test_sentinel_grid_mutations_require_owner_authorisation(monkeypatch) -> None:
    monkeypatch.setenv("AMOSCLAUD_OWNER_KEY", "owner-secret")
    industrial_autonomy.control_plane.reset()

    with TestClient(create_app()) as client:
        response = client.post(
            "/api/v1/sentinel-grid/assets",
            json={
                "name": "Untrusted Robot",
                "asset_type": "robot",
                "site": "test-site",
            },
        )

    assert response.status_code == 401


def test_telemetry_creates_critical_incident(monkeypatch) -> None:
    monkeypatch.setenv("AMOSCLAUD_OWNER_KEY", "owner-secret")
    industrial_autonomy.control_plane.reset()

    with TestClient(create_app()) as client:
        asset_id = _register_asset(client)
        response = client.post(
            "/api/v1/sentinel-grid/telemetry",
            headers=_headers(),
            json={
                "asset_id": asset_id,
                "metrics": {
                    "methane_ppm": 1200,
                    "battery_percent": 8,
                    "link_online": True,
                },
            },
        )

    assert response.status_code == 202
    incidents = response.json()["incidents"]
    assert {item["code"] for item in incidents} == {
        "battery_charge_low",
        "methane_threshold_exceeded",
    }
    critical = next(
        item for item in incidents if item["code"] == "methane_threshold_exceeded"
    )
    assert critical["risk"] == "critical"
    assert critical["recommended_action"] == "request_maintenance"


def test_physical_action_requires_approval_and_never_auto_executes(monkeypatch) -> None:
    monkeypatch.setenv("AMOSCLAUD_OWNER_KEY", "owner-secret")
    industrial_autonomy.control_plane.reset()

    with TestClient(create_app()) as client:
        asset_id = _register_asset(client)
        proposal = client.post(
            "/api/v1/sentinel-grid/actions",
            headers=_headers(),
            json={
                "asset_id": asset_id,
                "action_type": "move",
                "reason": "Reposition for a controlled inspection.",
                "requested_by": "amosclaud-autonomous",
            },
        )
        action = proposal.json()
        approval = client.post(
            f"/api/v1/sentinel-grid/actions/{action['action_id']}/approve",
            headers=_headers(),
            json={
                "decided_by": "owner-test",
                "note": "Approved for a future certified adapter.",
            },
        )

    assert proposal.status_code == 202
    assert action["status"] == "pending_approval"
    assert action["software_only"] is False
    assert action["execution_allowed"] is False
    assert approval.status_code == 200
    assert approval.json()["status"] == "approved"
    assert approval.json()["execution_allowed"] is False


def test_simulation_action_is_software_only(monkeypatch) -> None:
    monkeypatch.setenv("AMOSCLAUD_OWNER_KEY", "owner-secret")
    industrial_autonomy.control_plane.reset()

    with TestClient(create_app()) as client:
        asset_id = _register_asset(client)
        response = client.post(
            "/api/v1/sentinel-grid/actions",
            headers=_headers(),
            json={
                "asset_id": asset_id,
                "action_type": "simulate",
                "reason": "Test a maintenance route without commanding hardware.",
                "requested_by": "amosclaud-codex-agent",
            },
        )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "approved"
    assert body["software_only"] is True
    assert body["execution_allowed"] is False

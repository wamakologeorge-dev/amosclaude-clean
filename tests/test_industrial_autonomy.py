import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from amoscloud_ai.api.routes import industrial_autonomy
from amoscloud_ai.industrial_autonomy import (
    ActionStatus,
    AssetType,
    IncidentStatus,
    SentinelGridControlPlane,
)
from amoscloud_ai.main import create_app


def _headers() -> dict[str, str]:
    return {"X-Amosclaud-Owner-Key": "owner-secret"}


def _register_asset(
    client: TestClient,
    *,
    asset_type: str = "robot",
    capabilities: list[str] | None = None,
) -> str:
    response = client.post(
        "/api/v1/sentinel-grid/assets",
        headers=_headers(),
        json={
            "name": "Plant Inspection Asset 1",
            "asset_type": asset_type,
            "site": "test-site",
            "capabilities": capabilities or ["thermal-camera", "gas-sensor"],
        },
    )
    assert response.status_code == 201
    return response.json()["asset_id"]


def _sqlite_factory(path: Path):
    def connect() -> sqlite3.Connection:
        db = sqlite3.connect(path)
        db.row_factory = sqlite3.Row
        return db

    return connect


def test_sentinel_grid_status_exposes_safe_operating_pipeline(
    isolated_repository_data: Path,
) -> None:
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
    assert body["state_storage"] == "persistent_sqlite"


def test_sentinel_grid_state_survives_control_plane_recreation(tmp_path: Path) -> None:
    database_path = tmp_path / "sentinelgrid.db"
    first = SentinelGridControlPlane(_sqlite_factory(database_path))
    asset = first.register_asset(
        name="Persistent Robot",
        asset_type=AssetType.ROBOT,
        site="Plant A",
        capabilities=("thermal-camera",),
    )
    first.propose_action(
        asset_id=asset.asset_id,
        action_type="move",
        reason="Reposition for inspection.",
        requested_by="amosclaud-autonomous",
    )

    restarted = SentinelGridControlPlane(_sqlite_factory(database_path))

    assert restarted.list_assets()[0].asset_id == asset.asset_id
    assert restarted.list_actions()[0].asset_id == asset.asset_id


def test_sentinel_grid_mutations_require_owner_authorisation(
    monkeypatch,
    isolated_repository_data: Path,
) -> None:
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


def test_telemetry_numeric_strings_create_critical_incident(
    monkeypatch,
    isolated_repository_data: Path,
) -> None:
    monkeypatch.setenv("AMOSCLAUD_OWNER_KEY", "owner-secret")
    industrial_autonomy.control_plane.reset()

    with TestClient(create_app()) as client:
        asset_id = _register_asset(client)
        response = client.post(
            "/api/v1/sentinel-grid/telemetry",
            headers=_headers(),
            json={
                "asset_id": asset_id,
                "metrics":                     "methane_ppm": "1200",
                    "battery_percent": "8",
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
    critical = next(item for item in incidents if item["code"] == "methane_threshold_exceeded")
    assert critical["risk"] == "critical"
    assert critical["recommended_action"] == "request_maintenance"


def test_repeated_fault_is_coalesced_and_healthy_reading_resolves_it(
    monkeypatch,
    isolated_repository_data: Path,
) -> None:
    monkeypatch.setenv("AMOSCLAUD_OWNER_KEY", "owner-secret")
    industrial_autonomy.control_plane.reset()

    with TestClient(create_app()) as client:
        asset_id = _register_asset(client)
        first = client.post(
            "/api/v1/sentinel-grid/telemetry",
            headers=_headers(),
            json={"asset_id": asset_id, "metrics": {"methane_ppm": 1200}},
        )
        repeated = client.post(
            "/api/v1/sentinel-grid/telemetry",
            headers=_headers(),
            json={"asset_id": asset_id, "metrics": {"methane_ppm": 1300}},
        )
        healthy = client.post(
            "/api/v1/sentinel-grid/telemetry",
            headers=_headers(),
            json={"asset_id": asset_id, "metrics": {"methane_ppm": 20}},
        )
        open_incidents = client.get(
            "/api/v1/sentinel-grid/incidents?status=open",
            headers=_headers(),
        )
        resolved_incidents = client.get(
            "/api/v1/sentinel-grid/incidents?status=resolved",
            headers=_headers(),
        )
        status = client.get("/api/v1/sentinel-grid")

    assert first.status_code == 202
    assert repeated.status_code == 202
    first_incident = first.json()["incidents"][0]
    repeated_incident = repeated.json()["incidents"][0]
    assert repeated_incident["incident_id"] == first_incident["incident_id"]
    assert repeated_incident["occurrence_count"] == 2
    assert healthy.json()["incidents"] == []
    assert open_incidents.json() == []
    assert resolved_incidents.json()[0]["status"] == "resolved"
    assert status.json()["open_incidents"] == 0


def test_blank_normalized_asset_metadata_is_rejected(
    monkeypatch,
    isolated_repository_data: Path,
) -> None:
    monkeypatch.setenv("AMOSCLAUD_OWNER_KEY", "owner-secret")
    industrial_autonomy.control_plane.reset()

    with TestClient(create_app()) as client:
        response = client.post(
            "/api/v1/sentinel-grid/assets",
            headers=_headers(),
            json={
                "name": "  ",
                "asset_type": "robot",
                "site": "test-site",
            },
        )

    assert response.status_code == 422
    assert "non-whitespace" in response.json()["detail"]


def test_incompatible_physical_action_is_rejected(
    monkeypatch,
    isolated_repository_data: Path,
) -> None:
    monkeypatch.setenv("AMOSCLAUD_OWNER_KEY", "owner-secret")
    industrial_autonomy.control_plane.reset()

    with TestClient(create_app()) as client:
        asset_id = _register_asset(client, asset_type="sensor", capabilities=[])
        response = client.post(
            "/api/v1/sentinel-grid/actions",
            headers=_headers(),
            json={
                "asset_id": asset_id,
                "action_type": "move",
                "reason": "Move the stationary sensor.",
                "requested_by": "amosclaud-autonomous",
            },
        )

    assert response.status_code == 409
    assert "not supported" in response.json()["detail"]


def test_blank_action_reason_is_rejected_after_normalization(
    monkeypatch,
    isolated_repository_data: Path,
) -> None:
    monkeypatch.setenv("AMOSCLAUD_OWNER_KEY", "owner-secret")
    industrial_autonomy.control_plane.reset()

    with TestClient(create_app()) as client:
        asset_id = _register_asset(client)
        response = client.post(
            "/api/v1/sentinel-grid/actions",
            headers=_headers(),
            json={
                "asset_id": asset_id,
                "action_type": "move",
                "reason": "   ",
                "requested_by": "amosclaud-autonomous",
            },
        )

    assert response.status_code == 422
    assert "non-whitespace" in response.json()["detail"]


def test_physical_action_uses_authenticated_approver_and_never_auto_executes(
    monkeypatch,
    isolated_repository_data: Path,
) -> None:
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
                "decided_by": "forged-approver",
                "note": "Approved for a future certified adapter.",
            },
        )

    assert proposal.status_code == 202
    assert action["status"] == "pending_approval"
    assert action["software_only"] is False
    assert action["execution_allowed"] is False
    assert approval.status_code == 200
    assert approval.json()["status"] == "approved"
    assert approval.json()["decided_by"] == "amosclaud-owner-key"
    assert approval.json()["execution_allowed"] is False


def test_action_list_returns_stable_snapshots(tmp_path: Path) -> None:
    control_plane = SentinelGridControlPlane(_sqlite_factory(tmp_path / "sentinelgrid.db"))
    asset = control_plane.register_asset(
        name="Snapshot Robot",
        asset_type=AssetType.ROBOT,
        site="Plant A",
        capabilities=(),
    )
    proposal = control_plane.propose_action(
        asset_id=asset.asset_id,
        action_type="move",
        reason="Move to inspection bay.",
        requested_by="amosclaud-autonomous",
    )
    snapshot = control_plane.list_actions()[0]

    approved = control_plane.approve_action(
        proposal.action_id,
        decided_by="amosclaud-owner-key",
    )

    assert snapshot.status == ActionStatus.PENDING_APPROVAL
    assert snapshot.decided_at is None
    assert approved.status == ActionStatus.APPROVED
    assert approved.decided_at is not None


def test_unexpected_telemetry_failure_reaches_application_handler(
    monkeypatch,
    isolated_repository_data: Path,
) -> None:
    monkeypatch.setenv("AMOSCLAUD_OWNER_KEY", "owner-secret")
    industrial_autonomy.control_plane.reset()

    def fail_unexpectedly(**kwargs):
        del kwargs
        raise RuntimeError("unexpected test failure")

    monkeypatch.setattr(
        industrial_autonomy.control_plane,
        "record_telemetry",
        fail_unexpectedly,
    )
    with TestClient(create_app(), raise_server_exceptions=False) as client:
        response = client.post(
            "/api/v1/sentinel-grid/telemetry",
            headers=_headers(),
            json={
                "asset_id": "asset-12345678",
                "metrics": {"methane_ppm": 100},
            },
        )

    assert response.status_code == 500
    assert response.json()["error"] == "internal_server_error"


def test_simulation_action_is_software_only(
    monkeypatch,
    isolated_repository_data: Path,
) -> None:
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


def test_incident_status_enum_values_are_stable() -> None:
    assert IncidentStatus.OPEN.value == "open"
    assert IncidentStatus.RESOLVED.value == "resolved"

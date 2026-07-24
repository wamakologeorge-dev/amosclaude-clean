from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from amoscloud_ai.api.routes import agent_buddies, auth
from amoscloud_ai.main import create_app


def _owner(*_args, **_kwargs):
    return {"id": 42, "name": "Owner", "is_admin": 1}


def test_agent_buddy_status_is_truthful_and_heartbeat_driven(monkeypatch, tmp_path):
    auth.DB_PATH = tmp_path / "buddies.db"
    monkeypatch.setattr(agent_buddies, "_authorized_owner", _owner)
    client = TestClient(create_app())
    health = client.get("/api/v1/agent/buddies/health")
    assert health.status_code == 200
    initial = client.get("/api/v1/agent/buddies/status").json()
    assert initial["team_status"] == "offline"
    assert initial["responding"] is False
    assert initial["summary"] == {
        "total": 5,
        "online": 0,
        "blocked": 0,
        "offline_or_stale": 5,
    }

    heartbeat = client.post(
        "/api/v1/agent/buddies/builder/heartbeat",
        json={
            "name": "Builder Buddy",
            "role": "build verified patches",
            "status": "working",
            "capabilities": ["patch", "test", "patch"],
            "active_tasks": 1,
            "capacity": 3,
            "version": "1.2.0",
        },
    )
    assert heartbeat.status_code == 200
    assert heartbeat.json()["presence"] == "online"
    assert heartbeat.json()["available_slots"] == 2
    assert heartbeat.json()["capabilities"] == ["patch", "test"]

    status = client.get("/api/v1/agent/buddies/status").json()
    assert status["team_status"] == "degraded"
    assert status["summary"]["online"] == 1
    response = client.get("/api/v1/agent/buddies/status/respond").json()
    assert response["responding"] is True
    assert response["online_buddies"] == 1


def test_agent_buddy_stale_heartbeat_is_not_reported_online(monkeypatch, tmp_path):
    auth.DB_PATH = tmp_path / "buddies.db"
    monkeypatch.setattr(agent_buddies, "_authorized_owner", _owner)
    monkeypatch.setenv("AMOSCLAUD_BUDDY_ONLINE_SECONDS", "10")
    client = TestClient(create_app())
    client.post(
        "/api/v1/agent/buddies/verifier/heartbeat",
        json={"name": "Verifier", "role": "verify results", "status": "idle"},
    )
    old = (datetime.now(timezone.utc) - timedelta(seconds=20)).isoformat()
    with auth._connect() as db:
        db.execute(
            "UPDATE agent_buddy_heartbeats SET last_heartbeat_at=? WHERE buddy_id='verifier'",
            (old,),
        )
        db.commit()
    status = client.get("/api/v1/agent/buddies/status").json()
    verifier = next(item for item in status["buddies"] if item["buddy_id"] == "verifier")
    assert verifier["presence"] == "stale"
    assert verifier["responding"] is False

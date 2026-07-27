import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

from amoscloud_ai import model_network
from amoscloud_ai.api.routes import auth, server_stations
from amoscloud_ai.api.routes.task_router import RunnerCreate, RunnerHeartbeat


def _station(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "DB_PATH", tmp_path / "network.db")
    with auth._connect() as db:
        db.execute(
            "INSERT INTO users(name,email,password_hash,provider,is_admin,created_at) VALUES (?,?,?,?,?,?)",
            ("Network Owner", "network@example.com", None, "password", 1, server_stations._now()),
        )
        db.commit()
    monkeypatch.setattr(server_stations, "get_user_from_session", lambda _token: {"id": 1})
    monkeypatch.setenv("AMOSCLAUD_MASTER_KEY", "test-network-master-key")
    monkeypatch.setenv("AMOSCLAUD_NETWORK_OWNER_USER_ID", "1")
    created = server_stations.create_station(
        RunnerCreate(name="Model Station", capabilities=["model.inference"]), "session"
    )
    server_stations.station_heartbeat(
        created["id"],
        RunnerHeartbeat(
            version="1.0.1",
            capabilities=["model.inference"],
            system={"model": {"ready": True, "name": "amosclaud-folder-v1"}},
        ),
        f"Bearer {created['station_token']}",
    )
    return created


def test_outbound_station_claims_encrypted_inference(tmp_path, monkeypatch):
    station = _station(tmp_path, monkeypatch)
    result = {}

    def request():
        result["value"] = model_network.request_inference(
            [{"role": "user", "content": "private prompt"}], "system", timeout=3
        )

    thread = threading.Thread(target=request)
    thread.start()
    claimed = None
    for _ in range(100):
        claimed = model_network.claim_model_request(
            station["id"], f"Bearer {station['station_token']}"
        )
        if claimed:
            break
        time.sleep(0.01)
    assert claimed["messages"][-1]["content"] == "private prompt"
    model_network.complete_model_request(
        station["id"],
        claimed["id"],
        model_network.ModelCompletion(status="completed", reply="network answer"),
        f"Bearer {station['station_token']}",
    )
    thread.join(timeout=5)
    assert result["value"]["reply"] == "network answer"
    with auth._connect() as db:
        row = db.execute(
            "SELECT status,payload_ciphertext,response_ciphertext FROM model_network_requests"
        ).fetchone()
    assert tuple(row) == ("delivered", None, None)


def test_network_ignores_offline_or_untrusted_stations(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "DB_PATH", tmp_path / "empty.db")
    monkeypatch.setenv("AMOSCLAUD_MASTER_KEY", "test-network-master-key")
    monkeypatch.setenv("AMOSCLAUD_NETWORK_OWNER_USER_ID", "7")
    assert model_network.request_inference([], "system", timeout=1) is None
    assert model_network.network_status()["ready_stations"] == 0


def _queue_claimed_request(station, *, claimed=True):
    """Insert a model-network request directly, bypassing the HTTP claim flow."""
    request_id = "modelreq_" + uuid.uuid4().hex
    now = datetime.now(timezone.utc)
    with auth._connect() as db:
        model_network._ensure_network_schema(db)
        db.execute(
            """INSERT INTO model_network_requests
               (id,owner_user_id,station_id,status,payload_ciphertext,payload_hash,model,
                created_at,expires_at,claimed_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                request_id,
                1,
                station["id"] if claimed else None,
                "claimed" if claimed else "queued",
                model_network._encrypt({"messages": [], "model": "amosclaud-folder-v1"}),
                "hash",
                "amosclaud-folder-v1",
                now.isoformat(),
                (now + timedelta(minutes=10)).isoformat(),
                now.isoformat() if claimed else None,
            ),
        )
        db.commit()
    return request_id


def _row(db, request_id):
    return db.execute("SELECT * FROM model_network_requests WHERE id=?", (request_id,)).fetchone()


def test_recover_abandoned_claims_requeues_offline_station(tmp_path, monkeypatch):
    station = _station(tmp_path, monkeypatch)
    request_id = _queue_claimed_request(station)
    stale = (datetime.now(timezone.utc) - model_network.ONLINE_WINDOW * 3).isoformat()
    with auth._connect() as db:
        db.execute("UPDATE task_runners SET last_seen_at=? WHERE id=?", (stale, station["id"]))
        db.commit()
        model_network._recover_abandoned_claims(db)
        row = _row(db, request_id)
    assert row["status"] == "queued"
    assert row["station_id"] is None
    assert row["claimed_at"] is None
    assert row["payload_ciphertext"] is not None


def test_recover_abandoned_claims_requeues_revoked_station(tmp_path, monkeypatch):
    station = _station(tmp_path, monkeypatch)
    request_id = _queue_claimed_request(station)
    with auth._connect() as db:
        db.execute(
            "UPDATE task_runners SET revoked_at=? WHERE id=?",
            (model_network._now(), station["id"]),
        )
        db.commit()
        model_network._recover_abandoned_claims(db)
        row = _row(db, request_id)
    assert row["status"] == "queued"
    assert row["station_id"] is None


def test_recover_abandoned_claims_leaves_online_station_untouched(tmp_path, monkeypatch):
    station = _station(tmp_path, monkeypatch)
    request_id = _queue_claimed_request(station)
    with auth._connect() as db:
        # The station just heartbeat inside `_station`, so it is still online.
        model_network._recover_abandoned_claims(db)
        row = _row(db, request_id)
    assert row["status"] == "claimed"
    assert row["station_id"] == station["id"]
    assert row["payload_ciphertext"] is not None


def test_claim_route_expires_and_clears_payload_without_requeueing(tmp_path, monkeypatch):
    station = _station(tmp_path, monkeypatch)
    request_id = _queue_claimed_request(station, claimed=False)
    with auth._connect() as db:
        db.execute(
            "UPDATE model_network_requests SET expires_at=? WHERE id=?",
            ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), request_id),
        )
        db.commit()
    result = model_network.claim_model_request(station["id"], f"Bearer {station['station_token']}")
    assert result is None
    with auth._connect() as db:
        row = _row(db, request_id)
    assert row["status"] == "failed"
    assert row["payload_ciphertext"] is None


def test_complete_reports_409_when_no_longer_claimable(tmp_path, monkeypatch):
    station = _station(tmp_path, monkeypatch)
    request_id = _queue_claimed_request(station)
    with auth._connect() as db:
        db.execute("UPDATE model_network_requests SET status='failed' WHERE id=?", (request_id,))
        db.commit()
    try:
        model_network.complete_model_request(
            station["id"],
            request_id,
            model_network.ModelCompletion(status="completed", reply="too late"),
            f"Bearer {station['station_token']}",
        )
        raise AssertionError("expected HTTPException")
    except HTTPException as error:
        assert error.status_code == 409
        assert "status=failed" in error.detail


def test_complete_still_reports_404_for_unknown_request(tmp_path, monkeypatch):
    station = _station(tmp_path, monkeypatch)
    try:
        model_network.complete_model_request(
            station["id"],
            "modreq_never_existed",
            model_network.ModelCompletion(status="completed", reply="whatever"),
            f"Bearer {station['station_token']}",
        )
        raise AssertionError("expected HTTPException")
    except HTTPException as error:
        assert error.status_code == 404
        assert error.detail == "Claimed model request not found"

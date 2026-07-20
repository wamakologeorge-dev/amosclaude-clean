import threading
import time

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

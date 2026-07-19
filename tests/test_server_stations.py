from amoscloud_ai.api.routes import auth, server_stations
from amoscloud_ai.api.routes.task_router import RunnerCreate, RunnerHeartbeat


def _setup(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "DB_PATH", tmp_path / "auth.db")
    with auth._connect() as db:
        db.execute(
            "INSERT INTO users(name,email,password_hash,provider,is_admin,created_at) VALUES (?,?,?,?,?,?)",
            ("Owner", "owner@example.com", None, "password", 0, server_stations._now()),
        )
        db.commit()
    monkeypatch.setattr(server_stations, "get_user_from_session", lambda token: {"id": 1})


def test_station_lifecycle_and_one_time_token(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    created = server_stations.create_station(
        RunnerCreate(name="Build Station", capabilities=["build", "test"], labels=["linux"]),
        "session",
    )
    station_id = created["id"]
    token = created["station_token"]
    assert token.startswith("amos_station_")

    heartbeat = server_stations.station_heartbeat(
        station_id,
        RunnerHeartbeat(version="1.0.0", system={"os": "linux"}),
        f"Bearer {token}",
    )
    assert heartbeat["status"] == "online"
    station = server_stations.get_station(station_id, "session")
    assert station["system"] == {"os": "linux"}
    assert station["work"] == {"queued": 0, "running": 0, "completed": 0, "failed": 0}

    rotated = server_stations.rotate_station_token(station_id, "session")
    assert rotated["station_token"] != token
    server_stations.revoke_station(station_id, "session")
    assert server_stations.get_station(station_id, "session")["status"] == "revoked"


def test_station_access_is_owner_scoped(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    station_id = server_stations.create_station(RunnerCreate(name="Private Station"), "session")[
        "id"
    ]
    monkeypatch.setattr(server_stations, "get_user_from_session", lambda token: {"id": 2})
    try:
        server_stations.get_station(station_id, "other-session")
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 404
    else:
        raise AssertionError("A different owner must not see this station")

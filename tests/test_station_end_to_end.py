"""End-to-end proof that the station agent speaks the real Amosclaud protocol.

The real FastAPI application is served by uvicorn on localhost, a stub
Ollama backend stands in for the operator's hardware, and the agent is driven
exactly as it would be in production: register, heartbeat, claim, infer,
complete.
"""

from __future__ import annotations

import socket
import threading
import time
from datetime import datetime, timezone

import uvicorn

from amoscloud_ai import model_network
from amoscloud_ai.api.routes import auth, repositories, storage
from station.agent import StationAgent
from station.config import StationConfig
from station.register import register_station
from station.transport import request_json
from tests.station_stubs import free_port, ollama_routes, stub_server

MODEL = "qwen2.5-coder:1.5b"
REPLY = "Amosclaud routed this answer through a station on operator hardware."


def _wait_for_port(port: int, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as probe:
            probe.settimeout(0.5)
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.05)
    raise AssertionError(f"the platform did not start on port {port}")


def _serve_platform(tmp_path, monkeypatch):
    """Start the real Amosclaud FastAPI app on localhost and return its URL."""
    from amoscloud_ai import main

    db_path = tmp_path / "e2e-auth.db"
    monkeypatch.setattr(auth, "DB_PATH", db_path)
    monkeypatch.setattr(main, "DB_PATH", db_path)
    monkeypatch.setattr(repositories, "REPOSITORY_ROOT", tmp_path / "repositories")
    monkeypatch.setattr(storage, "STORAGE_ROOT", tmp_path / "storage")
    monkeypatch.setenv("AMOSCLAUD_MASTER_KEY", "station-end-to-end-master-key")
    monkeypatch.setenv("AMOSCLAUD_NETWORK_OWNER_USER_ID", "1")

    port = free_port()
    server = uvicorn.Server(
        uvicorn.Config(main.create_app(), host="127.0.0.1", port=port, log_level="error")
    )
    thread = threading.Thread(target=server.run, name="platform", daemon=True)
    thread.start()
    _wait_for_port(port)
    return f"http://127.0.0.1:{port}", server, thread, db_path


def _sign_in(db_path) -> str:
    with auth._connect() as db:
        db.execute(
            "INSERT INTO users(name,email,password_hash,provider,is_admin,created_at)"
            " VALUES (?,?,?,?,?,?)",
            (
                "Station Owner",
                "station-owner@example.com",
                None,
                "password",
                0,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        db.commit()
        return auth._create_session(db, 1)


def test_station_agent_completes_real_model_network_request(tmp_path, monkeypatch):
    base_url, server, server_thread, db_path = _serve_platform(tmp_path, monkeypatch)
    transcript: list[str] = []

    def note(line: str) -> None:
        transcript.append(line)

    try:
        session = _sign_in(db_path)
        note(f"platform: real FastAPI app on {base_url}")

        with stub_server(ollama_routes(MODEL, reply=REPLY)) as backend:
            note(f"backend:  stub Ollama on {backend.url} serving {MODEL}")

            # 1. Register through the real, session-authenticated route.
            created = register_station(
                base_url, session, "End to end station", ["model.inference"], ["e2e"]
            )
            station_id = created["id"]
            token = created["station_token"]
            assert station_id.startswith("station_")
            assert token.startswith("amos_station_")
            note(f"register: {station_id} credential=amos_station_***")

            config = StationConfig(
                station_id=station_id,
                station_token=token,
                base_url=base_url,
                backend_url=backend.url,
                model=MODEL,
                poll_interval=0.05,
                poll_max_interval=0.25,
                heartbeat_interval=5.0,
                http_timeout=10.0,
                probe_timeout=10.0,
                inference_timeout=20.0,
            ).normalised()
            agent = StationAgent(config)

            # 2. Heartbeat, then read the station back through the real API.
            assert agent.heartbeat_once() is True
            view = request_json(
                f"{base_url}/api/v1/server-stations/{station_id}",
                headers={"Cookie": f"amos_session={session}"},
                timeout=10,
            )
            note(
                "heartbeat: status={status} capabilities={capabilities} "
                "model.ready={ready}".format(
                    status=view["status"],
                    capabilities=view["capabilities"],
                    ready=view["system"]["model"]["ready"],
                )
            )
            assert view["status"] == "online"
            assert view["capabilities"] == ["model.inference"]
            assert view["system"]["model"]["ready"] is True

            status = model_network.network_status()
            note(f"network:  {status}")
            assert status == {"configured": True, "ready_stations": 1, "ready": True}

            # 3. Queue real work and let the agent pick it up.
            result: dict = {}

            def ask() -> None:
                result["value"] = model_network.request_inference(
                    [{"role": "user", "content": "what is the model station network"}],
                    "You are Amosclaud.",
                    timeout=30,
                )

            caller = threading.Thread(target=ask, name="request-inference")
            caller.start()
            runner = threading.Thread(
                target=agent.run, kwargs={"handle_signals": False}, name="station-agent"
            )
            runner.start()
            caller.join(timeout=60)
            agent.stop()
            runner.join(timeout=15)

            assert not caller.is_alive()
            answer = result.get("value")
            note(f"agent:    completed={agent.completed} failed={agent.failed}")
            note(f"result:   {answer}")
            assert answer is not None, "request_inference did not receive a station reply"
            assert answer["reply"] == REPLY
            assert answer["runtime"] == f"ollama:{MODEL}"

            # The exact payload reached the local backend, system prompt first.
            chats = [r for r in backend.requests if r["path"] == "/api/chat"]
            assert len(chats) == 1
            sent = chats[0]["body"]
            note(f"backend:  /api/chat model={sent['model']} options={sent['options']}")
            assert sent["model"] == MODEL
            assert sent["stream"] is False
            assert sent["messages"][0] == {"role": "system", "content": "You are Amosclaud."}
            assert sent["messages"][1] == {
                "role": "user",
                "content": "what is the model station network",
            }
            assert sent["options"] == {"temperature": 0.2, "num_predict": 1200}

            # The platform wiped the payload after delivery.
            with auth._connect() as db:
                row = db.execute(
                    "SELECT status,payload_ciphertext,response_ciphertext,runtime,station_id"
                    " FROM model_network_requests"
                ).fetchone()
            note(
                "database: status={0} payload={1} response={2} runtime={3}".format(
                    row["status"], row["payload_ciphertext"], row["response_ciphertext"],
                    row["runtime"],
                )
            )
            assert row["status"] == "delivered"
            assert row["payload_ciphertext"] is None
            assert row["response_ciphertext"] is None
            assert row["station_id"] == station_id
    finally:
        server.should_exit = True
        server_thread.join(timeout=15)

    # Run with `-s` to read the transcript; captured by default.
    print("\n--- station end-to-end transcript ---")
    for line in transcript:
        print(line)
    print("--- end transcript ---")

"""Tests for the Amosclaud Model Station agent (station/)."""

from __future__ import annotations

import io
import logging
import sys

import pytest

from station import healthcheck
from station.__main__ import main as station_main
from station.agent import ERROR, HANDLED, IDLE, StationAgent
from station.backend import BackendError, OllamaBackend
from station.config import ConfigError, StationConfig
from station.logs import configure_logging
from station.register import environment_block, register_station
from tests.station_stubs import free_port, ollama_routes, stub_server

MODEL = "qwen2.5-coder:1.5b"
TOKEN = "amos_station_TESTONLYcredential0123456789abcdef"
STATION_ID = "station_abc123"


def _config(platform_url: str, backend_url: str, **overrides) -> StationConfig:
    values = {
        "station_id": STATION_ID,
        "station_token": TOKEN,
        "base_url": platform_url,
        "backend_url": backend_url,
        "model": MODEL,
        "poll_interval": 0.01,
        "poll_max_interval": 0.05,
        "heartbeat_interval": 5.0,
        "http_timeout": 5.0,
        "probe_timeout": 5.0,
        "inference_timeout": 5.0,
    }
    values.update(overrides)
    return StationConfig(**values).normalised()


def _platform_routes(claim=None, complete=None, heartbeat=None) -> dict:
    return {
        ("POST", f"/api/v1/server-stations/{STATION_ID}/heartbeat"): heartbeat
        or (lambda _r: (200, {"ok": True, "station_id": STATION_ID, "status": "online"})),
        ("POST", f"/api/v1/model-network/stations/{STATION_ID}/claim"): claim
        or (lambda _r: (200, None)),
    }


def _complete_path(request_id: str) -> tuple[str, str]:
    return (
        "POST",
        f"/api/v1/model-network/stations/{STATION_ID}/requests/{request_id}/complete",
    )


# --------------------------------------------------------------------- config


def test_config_requires_station_identity_and_credential():
    with pytest.raises(ConfigError) as missing_id:
        StationConfig.from_env({})
    assert "AMOSCLAUD_STATION_ID" in str(missing_id.value)

    with pytest.raises(ConfigError) as missing_token:
        StationConfig.from_env({"AMOSCLAUD_STATION_ID": STATION_ID})
    assert "AMOSCLAUD_STATION_TOKEN" in str(missing_token.value)


def test_config_defaults_and_online_window_safety():
    config = StationConfig.from_env(
        {"AMOSCLAUD_STATION_ID": STATION_ID, "AMOSCLAUD_STATION_TOKEN": TOKEN}
    )
    assert config.base_url == "https://www.amosclaud.com"
    assert config.backend_url == "http://127.0.0.1:11434"
    assert config.model == MODEL
    assert config.capabilities == ("model.inference",)
    assert config.heartbeat_interval == 30.0
    assert config.claim_url == (
        f"https://www.amosclaud.com/api/v1/model-network/stations/{STATION_ID}/claim"
    )
    assert config.complete_url("modelreq_1").endswith(
        f"/model-network/stations/{STATION_ID}/requests/modelreq_1/complete"
    )
    # The platform only treats a station as online for 90 seconds, so a
    # configured cadence that would let the window lapse is clamped.
    slow = StationConfig.from_env(
        {
            "AMOSCLAUD_STATION_ID": STATION_ID,
            "AMOSCLAUD_STATION_TOKEN": TOKEN,
            "AMOSCLAUD_STATION_HEARTBEAT_INTERVAL": "600",
        }
    )
    assert slow.heartbeat_interval == 30.0
    assert "station_token" not in config.summary()
    assert TOKEN not in repr(config.summary())


# ------------------------------------------------------------------ heartbeat


def test_heartbeat_advertises_inference_and_truthful_ready_model():
    with stub_server(ollama_routes(MODEL)) as backend, stub_server(
        _platform_routes()
    ) as platform:
        agent = StationAgent(_config(platform.url, backend.url))
        assert agent.heartbeat_once() is True

    sent = platform.requests[0]
    assert sent["method"] == "POST"
    assert sent["path"] == f"/api/v1/server-stations/{STATION_ID}/heartbeat"
    assert sent["headers"]["Authorization"] == f"Bearer {TOKEN}"
    assert sent["headers"]["Content-Type"] == "application/json"
    assert sent["body"]["capabilities"] == ["model.inference"]
    assert sent["body"]["version"].startswith("amosclaud-station/")
    model = sent["body"]["system"]["model"]
    assert model["ready"] is True
    assert model["name"] == MODEL
    assert model["backend"] == "ollama"
    assert backend.requests[0]["path"] == "/api/tags"


def test_heartbeat_reports_not_ready_when_model_is_missing():
    routes = ollama_routes(MODEL, tags=lambda _r: (200, {"models": [{"name": "llama3:8b"}]}))
    with stub_server(routes) as backend, stub_server(_platform_routes()) as platform:
        agent = StationAgent(_config(platform.url, backend.url))
        assert agent.heartbeat_once() is True

    model = platform.requests[0]["body"]["system"]["model"]
    assert model["ready"] is False
    assert MODEL in model["detail"]
    assert "not installed" in model["detail"]


def test_heartbeat_reports_not_ready_when_backend_is_unreachable():
    closed = free_port()
    with stub_server(_platform_routes()) as platform:
        agent = StationAgent(_config(platform.url, f"http://127.0.0.1:{closed}"))
        assert agent.heartbeat_once() is True
        # A station that cannot infer must never claim work.
        assert agent.poll_once() == "not_ready"

    model = platform.requests[0]["body"]["system"]["model"]
    assert model["ready"] is False
    assert "unreachable" in model["detail"]
    assert platform.requests[0]["body"]["capabilities"] == ["model.inference"]


# ----------------------------------------------------------------- round trip


def test_claim_infer_complete_round_trip():
    request_id = "modelreq_roundtrip"
    queue = [
        {
            "id": request_id,
            "messages": [
                {"role": "system", "content": "You are Amosclaud."},
                {"role": "user", "content": "explain the station network"},
            ],
            "model": "amosclaud-folder-v1",
            "max_tokens": 1200,
            "temperature": 0.2,
        }
    ]
    routes = _platform_routes(claim=lambda _r: (200, queue.pop(0) if queue else None))
    routes[_complete_path(request_id)] = lambda _r: (
        200,
        {"ok": True, "request_id": request_id, "status": "completed"},
    )
    with stub_server(ollama_routes(MODEL, reply="the station answers")) as backend, stub_server(
        routes
    ) as platform:
        agent = StationAgent(_config(platform.url, backend.url))
        agent.probe_backend()
        assert agent.poll_once() == HANDLED
        assert agent.poll_once() == IDLE
        assert agent.completed == 1
        assert agent.failed == 0

    claim = platform.requests[0]
    completions = [r for r in platform.requests if r["path"].endswith("/complete")]
    assert len(completions) == 1
    complete = completions[0]
    assert claim["path"] == f"/api/v1/model-network/stations/{STATION_ID}/claim"
    assert claim["headers"]["Authorization"] == f"Bearer {TOKEN}"
    assert complete["path"] == (
        f"/api/v1/model-network/stations/{STATION_ID}/requests/{request_id}/complete"
    )
    assert complete["headers"]["Authorization"] == f"Bearer {TOKEN}"
    assert complete["body"] == {
        "status": "completed",
        "reply": "the station answers",
        "runtime": f"ollama:{MODEL}",
        "error": None,
    }

    chat = [r for r in backend.requests if r["path"] == "/api/chat"][0]
    assert chat["method"] == "POST"
    assert chat["body"] == {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": "You are Amosclaud."},
            {"role": "user", "content": "explain the station network"},
        ],
        "stream": False,
        "options": {"temperature": 0.2, "num_predict": 1200},
    }


def test_generate_endpoint_is_used_when_chat_is_unavailable():
    routes = ollama_routes(MODEL)
    routes[("POST", "/api/chat")] = lambda _r: (404, {"error": "not found"})
    routes[("POST", "/api/generate")] = lambda _r: (200, {"response": "legacy reply"})
    with stub_server(routes) as backend:
        client = OllamaBackend(backend.url, MODEL, chat_timeout=5, probe_timeout=5)
        reply = client.chat(
            [{"role": "user", "content": "hi"}], temperature=0.5, max_tokens=64
        )
    assert reply == "legacy reply"
    generate = [r for r in backend.requests if r["path"] == "/api/generate"][0]
    assert generate["body"]["model"] == MODEL
    assert generate["body"]["prompt"].startswith("user: hi")
    assert generate["body"]["options"] == {"temperature": 0.5, "num_predict": 64}


def test_backend_error_when_reply_is_empty():
    routes = ollama_routes(MODEL, reply="   ")
    with stub_server(routes) as backend:
        client = OllamaBackend(backend.url, MODEL, chat_timeout=5, probe_timeout=5)
        with pytest.raises(BackendError):
            client.chat([{"role": "user", "content": "hi"}])


# -------------------------------------------------------------------- failure


def _failure_case(chat_route):
    request_id = "modelreq_failure"
    queue = [{"id": request_id, "messages": [{"role": "user", "content": "hi"}],
              "model": "amosclaud-folder-v1", "max_tokens": 100, "temperature": 0.2}]
    routes = _platform_routes(claim=lambda _r: (200, queue.pop(0) if queue else None))
    routes[_complete_path(request_id)] = lambda _r: (200, {"ok": True})
    backend_routes = ollama_routes(MODEL)
    backend_routes[("POST", "/api/chat")] = chat_route
    with stub_server(backend_routes) as backend, stub_server(routes) as platform:
        agent = StationAgent(_config(platform.url, backend.url))
        agent.probe_backend()
        assert agent.poll_once() == HANDLED
        assert agent.failed == 1
        assert agent.completed == 0
    return platform.requests[-1]["body"]


def test_late_completion_409_is_logged_as_expired_not_a_generic_failure(caplog):
    request_id = "modelreq_late"
    queue = [{"id": request_id, "messages": [{"role": "user", "content": "hi"}],
              "model": "amosclaud-folder-v1", "max_tokens": 100, "temperature": 0.2}]
    routes = _platform_routes(claim=lambda _r: (200, queue.pop(0) if queue else None))
    routes[_complete_path(request_id)] = lambda _r: (
        409,
        {"detail": "Model request is no longer claimable (status=failed)"},
    )
    with stub_server(ollama_routes(MODEL, reply="a reply")) as backend, stub_server(
        routes
    ) as platform:
        agent = StationAgent(_config(platform.url, backend.url))
        agent.probe_backend()
        with caplog.at_level("WARNING", logger=agent.log.name):
            outcome = agent.poll_once()
        # A late completion is not a crash and not a generic failure: the
        # station simply moves on to its next poll cycle.
        assert outcome == HANDLED
        assert agent.completed == 0
        assert agent.failed == 0
        # It should be logged as expired/no-longer-claimable, and only once
        # (no tight retry loop), and never with the bearer token in it.
        completions = [r for r in platform.requests if r["path"].endswith("/complete")]
        assert len(completions) == 1
    messages = [record.getMessage() for record in caplog.records]
    assert any("no longer claimable" in message for message in messages)
    assert not any(TOKEN in message for message in messages)
    assert not any("completion rejected" in message for message in messages)

    # The loop keeps running normally afterwards.
    with stub_server(ollama_routes(MODEL)) as backend, stub_server(
        _platform_routes()
    ) as platform:
        agent = StationAgent(_config(platform.url, backend.url))
        agent.probe_backend()
        assert agent.run(handle_signals=False, max_cycles=2) == 2


def test_backend_error_is_reported_as_failed_completion():
    body = _failure_case(lambda _r: (500, {"error": "cuda out of memory"}))
    assert body["status"] == "failed"
    assert body["reply"] is None
    assert body["error"]
    assert "backend chat failed" in body["error"]


def test_empty_backend_reply_is_reported_as_failed_not_dropped():
    body = _failure_case(lambda _r: (200, {"message": {"role": "assistant", "content": ""}}))
    assert body["status"] == "failed"
    assert body["reply"] is None
    assert "empty reply" in body["error"]


# ----------------------------------------------------------------- resilience


def test_server_errors_and_refused_connections_do_not_kill_the_loop():
    attempts = {"count": 0}

    def flaky_claim(_record):
        attempts["count"] += 1
        if attempts["count"] <= 2:
            return 500, {"detail": "internal server error"}
        return 200, None

    with stub_server(ollama_routes(MODEL)) as backend, stub_server(
        _platform_routes(claim=flaky_claim)
    ) as platform:
        agent = StationAgent(_config(platform.url, backend.url))
        agent.probe_backend()
        assert agent.poll_once() == ERROR
        assert agent.poll_once() == ERROR
        assert agent.poll_once() == IDLE
        # The full loop keeps running across the same failures.
        cycles = agent.run(handle_signals=False, max_cycles=3)
        assert cycles == 3
        assert agent.heartbeats >= 1

        # A platform that is not listening at all is also survivable.
        offline = StationAgent(_config(f"http://127.0.0.1:{free_port()}", backend.url))
        offline.probe_backend()
        assert offline.heartbeat_once() is False
        assert offline.poll_once() == ERROR
        assert offline.run(handle_signals=False, max_cycles=2) == 2

    assert attempts["count"] >= 3


def test_idle_polling_backs_off_and_resets_on_work():
    config = _config("http://127.0.0.1:1", "http://127.0.0.1:1",
                     poll_interval=1.0, poll_max_interval=8.0)
    agent = StationAgent(config)
    first = agent.next_interval(IDLE)
    second = agent.next_interval(IDLE)
    assert 1.0 <= first < second <= 8.0
    # Errors back off faster, and never beyond the configured ceiling.
    assert second < agent.next_interval(ERROR) <= 8.0
    for _ in range(10):
        assert agent.next_interval(IDLE) <= 8.0
    # Real work resets the cadence to the fast poll interval.
    assert agent.next_interval(HANDLED) == 0.0
    assert agent.next_interval(IDLE) == pytest.approx(1.5)


# --------------------------------------------------------------------- secrets


def test_station_token_never_appears_in_log_output():
    stream = io.StringIO()
    logger = configure_logging(
        "DEBUG", secrets=[TOKEN], stream=stream, logger_name="amosclaud.station.test"
    )
    request_id = "modelreq_logsafe"
    queue = [{"id": request_id, "messages": [{"role": "user", "content": "secret prompt"}],
              "model": "amosclaud-folder-v1", "max_tokens": 32, "temperature": 0.1}]
    routes = _platform_routes(claim=lambda _r: (200, queue.pop(0) if queue else None))
    routes[_complete_path(request_id)] = lambda _r: (401, {"detail": f"bad token {TOKEN}"})
    try:
        with stub_server(ollama_routes(MODEL, reply="secret reply")) as backend, stub_server(
            routes
        ) as platform:
            agent = StationAgent(_config(platform.url, backend.url), logger=logger)
            agent.heartbeat_once()
            agent.poll_once()
            # Even a direct attempt to log the credential is scrubbed.
            logger.error("credential leak attempt %s", TOKEN)
            logger.info("station %s reporting", platform.url)
    finally:
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()

    output = stream.getvalue()
    assert output.strip()
    assert TOKEN not in output
    assert "***redacted***" in output
    assert "secret prompt" not in output
    assert "secret reply" not in output
    assert request_id in output


# -------------------------------------------------- registration and packaging


def test_registration_helper_posts_to_the_real_route_and_prints_env_once(capsys):
    created = {
        "id": STATION_ID,
        "name": "Studio station",
        "station_token": TOKEN,
        "warning": "Copy this credential now.",
    }
    routes = {("POST", "/api/v1/server-stations"): lambda _r: (201, created)}
    with stub_server(routes) as platform:
        result = register_station(
            platform.url, "session-cookie-value", "Studio station", ["model.inference"], ["gpu"]
        )
    request = platform.requests[0]
    assert request["path"] == "/api/v1/server-stations"
    assert request["headers"]["Cookie"] == "amos_session=session-cookie-value"
    assert request["body"] == {
        "name": "Studio station",
        "capabilities": ["model.inference"],
        "labels": ["gpu"],
    }
    assert result["station_token"] == TOKEN

    block = environment_block(platform.url, STATION_ID, TOKEN, "http://127.0.0.1:11434", MODEL)
    assert block.count(TOKEN) == 1
    assert f"AMOSCLAUD_STATION_ID={STATION_ID}" in block
    assert f"AMOSCLAUD_STATION_MODEL={MODEL}" in block
    capsys.readouterr()


def test_entry_point_refuses_to_start_without_configuration(monkeypatch, capsys):
    for name in ("AMOSCLAUD_STATION_ID", "AMOSCLAUD_STATION_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    assert station_main([]) == 2
    assert "AMOSCLAUD_STATION_ID is required" in capsys.readouterr().err
    assert station_main(["--help"]) == 0


def test_container_healthcheck_tracks_backend_readiness():
    with stub_server(ollama_routes(MODEL)) as backend:
        env = {"AMOSCLAUD_STATION_BACKEND": backend.url, "AMOSCLAUD_STATION_MODEL": MODEL}
        assert healthcheck.main(env) == 0
    assert healthcheck.main(
        {
            "AMOSCLAUD_STATION_BACKEND": f"http://127.0.0.1:{free_port()}",
            "AMOSCLAUD_STATION_MODEL": MODEL,
        }
    ) == 1


def test_agent_package_uses_only_the_standard_library():
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parent.parent / "station"
    allowed = {"station"} | set(sys.stdlib_module_names)
    for source in sorted(root.glob("*.py")):
        for match in re.finditer(
            r"^\s*(?:from\s+([a-zA-Z_][\w.]*)|import\s+([a-zA-Z_][\w.]*))",
            source.read_text(encoding="utf-8"),
            re.MULTILINE,
        ):
            module = (match.group(1) or match.group(2)).split(".")[0]
            assert module in allowed, f"{source.name} imports third-party module {module}"
    dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")
    assert "python:3.12-slim" in dockerfile
    assert "USER station" in dockerfile
    assert (root / "README.md").exists()


def test_logging_configuration_is_idempotent_and_scrubs_exceptions():
    stream = io.StringIO()
    logger = configure_logging(
        "INFO", secrets=[TOKEN], stream=stream, logger_name="amosclaud.station.test2"
    )
    configure_logging(
        "INFO", secrets=[TOKEN], stream=stream, logger_name="amosclaud.station.test2"
    )
    assert len(logger.handlers) == 1
    try:
        raise RuntimeError(f"failed with {TOKEN}")
    except RuntimeError:
        logger.exception("inference failed")
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    assert TOKEN not in stream.getvalue()
    assert logging.getLogger("amosclaud.station.test2").level == logging.INFO

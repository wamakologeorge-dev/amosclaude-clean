import sqlite3
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from amosclaud_metrics.collectors import database_metrics
from amosclaud_metrics.integration import install_metrics
from amosclaud_metrics.registry import Registry
from amosclaud_metrics.history import HistoryStore


def test_registry_renders_bounded_labels_and_escaping():
    registry = Registry()
    registry.counter(
        "amosclaud_requests_total",
        help_text="Requests",
        labels={"route": '/tasks/"safe"', "status": "200"},
    )
    output = registry.render({"amosclaud_up": 1})
    assert "# TYPE amosclaud_requests_total counter" in output
    assert 'route="/tasks/\\"safe\\""' in output
    assert "amosclaud_up 1" in output


def test_database_collector_is_read_only_and_tolerates_partial_schema(tmp_path):
    path = tmp_path / "auth.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE users(id INTEGER PRIMARY KEY)")
        db.executemany("INSERT INTO users(id) VALUES (?)", [(1,), (2,)])
        db.commit()
    metrics = database_metrics(path)
    assert metrics["amosclaud_database_reachable"] == 1
    assert metrics["amosclaud_users_total"] == 2
    assert metrics["amosclaud_tasks_running"] == 0


def test_application_instrumentation_uses_route_templates(monkeypatch):
    monkeypatch.delenv("AMOSCLAUD_METRICS_TOKEN", raising=False)
    app = FastAPI()
    install_metrics(app)

    @app.get("/items/{item_id}")
    def item(item_id: str):
        return {"id": item_id}

    with TestClient(app) as client:
        assert client.get("/items/private-object-id").status_code == 200
        output = client.get("/metrics").text
    assert 'route="/items/{item_id}"' in output
    assert "private-object-id" not in output


def test_metrics_server_auth_summary_and_ssy(tmp_path, monkeypatch):
    path = tmp_path / "auth.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE users(id INTEGER PRIMARY KEY)")
        db.execute("INSERT INTO users VALUES (1)")
        db.commit()
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("AUTH_DB_PATH", str(path))
    monkeypatch.setenv("AMOSCLAUD_METRICS_DB", str(tmp_path / "metrics.db"))
    monkeypatch.setenv("AMOSCLAUD_METRICS_TOKEN", "metrics-secret")
    from amosclaud_metrics import server

    monkeypatch.setattr(server, "service_health", lambda url: (1.0, 0.01))
    monkeypatch.setattr(
        server, "scrape_metrics", lambda url, token: "amosclaud_http_requests_total 2\n"
    )
    with TestClient(server.create_app()) as client:
        assert client.get("/metrics").status_code == 401
        headers = {"Authorization": "Bearer metrics-secret"}
        metrics = client.get("/metrics", headers=headers)
        summary = client.get("/v1/summary", headers=headers)
        ssy = client.get("/v1/ssy", headers=headers)
        alerts = client.get("/v1/alerts", headers=headers)
        history = client.get("/v1/history", headers=headers)
    assert metrics.status_code == 200
    assert "amosclaud_http_requests_total 2" in metrics.text
    assert summary.json()["services"]["model"]["up"] is True
    assert ssy.json()["short_name"] == "SSY"
    assert alerts.json()["active"] == 0
    assert history.json()["count"] >= 1


def test_production_metrics_server_requires_token(monkeypatch):
    from amosclaud_metrics import server

    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("AMOSCLAUD_METRICS_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="required"):
        server.create_app()


def test_history_store_records_and_limits_snapshots(tmp_path):
    store = HistoryStore(tmp_path / "history.db")
    now = time.time()
    for timestamp in (now + 1, now + 2, now + 3):
        store.record({"collected_at_unix": timestamp, "status": "healthy", "metrics": {}})
    recent = store.recent(2)
    assert [item["collected_at_unix"] for item in recent] == [now + 3, now + 2]

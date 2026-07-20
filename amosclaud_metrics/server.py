"""Standalone Amosclaud Metrics Server and System Service Yard (SSY)."""
from __future__ import annotations

import asyncio
import hmac
import os
import threading
import time
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import PlainTextResponse

from amosclaud_metrics import __version__
from amosclaud_metrics.collectors import database_metrics, scrape_metrics, service_health, system_metrics
from amosclaud_metrics.history import HistoryStore
from amosclaud_metrics.platform import collect_platform_snapshot
from amosclaud_metrics.registry import Registry


class SnapshotCache:
    def __init__(self, ttl: float = 5):
        self.ttl = ttl
        self.lock = threading.Lock()
        self.created = 0.0
        self.value: dict = {}

    def get(self) -> dict:
        with self.lock:
            if time.monotonic() - self.created < self.ttl:
                return self.value
            self.value = collect_snapshot()
            self.created = time.monotonic()
            return self.value


def _token() -> str:
    return os.getenv("AMOSCLAUD_METRICS_TOKEN", "").strip()


def authorize(authorization: str | None = Header(default=None)) -> None:
    expected = _token()
    if expected and (not authorization or not hmac.compare_digest(authorization, f"Bearer {expected}")):
        raise HTTPException(status_code=401, detail="Invalid metrics credential")


def collect_snapshot() -> dict:
    api_url = os.getenv("AMOSCLAUD_API_HEALTH_URL", "http://amosclaud:8000/health")
    model_url = os.getenv("AMOSCLAUD_MODEL_HEALTH_URL", "http://model:8091/health")
    api_up, api_latency = service_health(api_url)
    model_up, model_latency = service_health(model_url)
    platform = collect_platform_snapshot()
    values = {
        **system_metrics(),
        **database_metrics(Path(os.getenv("AUTH_DB_PATH", "/data/auth.db"))),
        **platform["metrics"],
        "amosclaud_api_up": api_up,
        "amosclaud_api_probe_duration_seconds": api_latency,
        "amosclaud_model_up": model_up,
        "amosclaud_model_probe_duration_seconds": model_latency,
    }
    services = {
        "api": {"up": bool(api_up), "latency_ms": round(api_latency * 1000, 2)},
        "model": {"up": bool(model_up), "latency_ms": round(model_latency * 1000, 2)},
        "database": {"up": bool(values["amosclaud_database_reachable"])},
        **platform["services"],
    }
    required_up = (
        bool(api_up)
        and bool(values["amosclaud_database_reachable"])
        and platform["status"] == "healthy"
    )
    return {
        "status": "healthy" if required_up else "degraded",
        "services": services,
        "metrics": values,
        "collected_at_unix": time.time(),
    }


def active_alerts(snapshot: dict) -> list[dict]:
    metrics = snapshot["metrics"]
    alerts: list[dict] = []
    for service, evidence in snapshot["services"].items():
        if not evidence.get("up"):
            severity = "critical" if service in {
                "api", "database", "platform_database", "repository_storage", "api_gateway"
            } else "warning"
            alerts.append(
                {
                    "code": f"{service}_down",
                    "severity": severity,
                    "message": f"Amosclaud {service.replace('_', ' ')} is unavailable or unconfigured",
                }
            )
    total_memory = metrics.get("amosclaud_system_memory_bytes", 0)
    available_memory = metrics.get("amosclaud_system_memory_available_bytes", 0)
    if total_memory and available_memory / total_memory < 0.1:
        alerts.append(
            {"code": "memory_low", "severity": "warning", "message": "Available memory is below 10%"}
        )
    total_disk = metrics.get("amosclaud_system_disk_bytes", 0)
    free_disk = metrics.get("amosclaud_system_disk_free_bytes", 0)
    if total_disk and free_disk / total_disk < 0.1:
        alerts.append(
            {"code": "disk_low", "severity": "critical", "message": "Free disk space is below 10%"}
        )
    if metrics.get("amosclaud_webhook_deliveries_failed", 0):
        alerts.append(
            {
                "code": "webhook_failures",
                "severity": "warning",
                "message": "Webhook deliveries need attention",
            }
        )
    if metrics.get("amosclaud_ci_pipelines_failed", 0):
        alerts.append(
            {
                "code": "ci_failures",
                "severity": "warning",
                "message": "One or more Amosclaud CI pipelines have failed",
            }
        )
    if metrics.get("amosclaud_autonomous_jobs_failed", 0):
        alerts.append(
            {
                "code": "autonomous_job_failures",
                "severity": "warning",
                "message": "One or more Autonomous or Fixer jobs need attention",
            }
        )
    return alerts


def create_app() -> FastAPI:
    if os.getenv("ENVIRONMENT", "development").lower() in {"production", "prod"} and not _token():
        raise RuntimeError("AMOSCLAUD_METRICS_TOKEN is required in production")
    cache = SnapshotCache(float(os.getenv("AMOSCLAUD_METRICS_CACHE_SECONDS", "5")))
    exposition = Registry()
    history = HistoryStore(
        Path(os.getenv("AMOSCLAUD_METRICS_DB", "data/metrics.db")),
        int(os.getenv("AMOSCLAUD_METRICS_RETENTION_DAYS", "7")),
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        history.initialize()

        async def sample() -> None:
            while True:
                snapshot = await asyncio.to_thread(cache.get)
                await asyncio.to_thread(history.record, snapshot)
                await asyncio.sleep(float(os.getenv("AMOSCLAUD_METRICS_SAMPLE_SECONDS", "15")))

        task = asyncio.create_task(sample())
        yield
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    app = FastAPI(title="Amosclaud Metrics Server", version=__version__, lifespan=lifespan)

    @app.get("/health")
    def health() -> dict:
        snapshot = cache.get()
        return {"status": snapshot["status"], "service": "amosclaud-metrics", "version": __version__}

    @app.get("/metrics", dependencies=[Depends(authorize)])
    def metrics() -> PlainTextResponse:
        application = scrape_metrics(
            os.getenv("AMOSCLAUD_API_METRICS_URL", "http://amosclaud:8000/metrics"), _token()
        )
        snapshot = cache.get()
        values = {**snapshot["metrics"], "amosclaud_alerts_active": len(active_alerts(snapshot))}
        return PlainTextResponse(
            exposition.render(values) + application,
            media_type="text/plain; version=0.0.4",
        )

    @app.get("/v1/summary", dependencies=[Depends(authorize)])
    def summary() -> dict:
        return cache.get()

    @app.get("/v1/ssy", dependencies=[Depends(authorize)])
    def system_service_yard() -> dict:
        snapshot = cache.get()
        return {
            "name": "Amosclaud System Service Yard",
            "short_name": "SSY",
            "status": snapshot["status"],
            "services": snapshot["services"],
            "stations": int(snapshot["metrics"].get("amosclaud_stations_registered", 0)),
            "repositories": int(snapshot["metrics"].get("amosclaud_repositories_total", 0)),
            "autonomous_jobs": {
                key.removeprefix("amosclaud_autonomous_jobs_"): int(value)
                for key, value in snapshot["metrics"].items()
                if key.startswith("amosclaud_autonomous_jobs_")
            },
            "ci_pipelines": {
                key.removeprefix("amosclaud_ci_pipelines_"): int(value)
                for key, value in snapshot["metrics"].items()
                if key.startswith("amosclaud_ci_pipelines_")
            },
            "tasks": {
                key.removeprefix("amosclaud_tasks_"): int(value)
                for key, value in snapshot["metrics"].items()
                if key.startswith("amosclaud_tasks_")
            },
        }

    @app.get("/v1/alerts", dependencies=[Depends(authorize)])
    def alerts() -> dict:
        items = active_alerts(cache.get())
        return {"active": len(items), "alerts": items}

    @app.get("/v1/history", dependencies=[Depends(authorize)])
    def metric_history(limit: int = 100) -> dict:
        items = history.recent(max(1, min(limit, 1000)))
        return {"count": len(items), "snapshots": items}

    return app


app = create_app()


def main() -> None:
    import uvicorn

    uvicorn.run(
        "amosclaud_metrics.server:app",
        host=os.getenv("METRICS_HOST", "127.0.0.1"),
        port=int(os.getenv("METRICS_PORT", "9090")),
    )

from __future__ import annotations

import os
import shutil
import sqlite3
import time
from pathlib import Path

import httpx


def system_metrics() -> dict[str, float]:
    metrics: dict[str, float] = {}
    try:
        one, five, fifteen = os.getloadavg()
        metrics.update(
            amosclaud_system_load_1=one,
            amosclaud_system_load_5=five,
            amosclaud_system_load_15=fifteen,
        )
    except OSError:
        pass
    memory = Path("/proc/meminfo")
    if memory.exists():
        values = {}
        for line in memory.read_text(encoding="utf-8").splitlines():
            key, value = line.split(":", 1)
            values[key] = float(value.strip().split()[0]) * 1024
        metrics["amosclaud_system_memory_bytes"] = values.get("MemTotal", 0)
        metrics["amosclaud_system_memory_available_bytes"] = values.get("MemAvailable", 0)
    uptime = Path("/proc/uptime")
    if uptime.exists():
        metrics["amosclaud_system_uptime_seconds"] = float(uptime.read_text().split()[0])
    disk = shutil.disk_usage(
        os.getenv("DATA_DIR", "/data") if Path(os.getenv("DATA_DIR", "/data")).exists() else "."
    )
    metrics["amosclaud_system_disk_bytes"] = disk.total
    metrics["amosclaud_system_disk_free_bytes"] = disk.free
    return metrics


def database_metrics(path: Path) -> dict[str, float]:
    metrics: dict[str, float] = {"amosclaud_database_reachable": 0}
    if not path.exists():
        return metrics
    queries = {
        "amosclaud_users_total": "SELECT COUNT(*) FROM users",
        "amosclaud_sessions_active": "SELECT COUNT(*) FROM sessions WHERE expires_at > datetime('now')",
        "amosclaud_tasks_queued": "SELECT COUNT(*) FROM global_tasks WHERE status='queued'",
        "amosclaud_tasks_running": "SELECT COUNT(*) FROM global_tasks WHERE status='running'",
        "amosclaud_tasks_completed": "SELECT COUNT(*) FROM global_tasks WHERE status='completed'",
        "amosclaud_tasks_failed": "SELECT COUNT(*) FROM global_tasks WHERE status='failed'",
        "amosclaud_stations_registered": "SELECT COUNT(*) FROM task_runners WHERE revoked_at IS NULL",
        "amosclaud_webhooks_active": "SELECT COUNT(*) FROM developer_webhooks WHERE status='active'",
        "amosclaud_webhook_deliveries_failed": "SELECT COUNT(*) FROM webhook_deliveries WHERE status='failed'",
    }
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2) as db:
            metrics["amosclaud_database_reachable"] = 1
            for name, query in queries.items():
                try:
                    metrics[name] = float(db.execute(query).fetchone()[0])
                except sqlite3.OperationalError:
                    metrics[name] = 0
    except sqlite3.Error:
        pass
    return metrics


def service_health(url: str, timeout: float = 2) -> tuple[float, float]:
    started = time.monotonic()
    try:
        response = httpx.get(url, timeout=timeout, follow_redirects=False)
        return (1.0 if response.is_success else 0.0, time.monotonic() - started)
    except httpx.HTTPError:
        return (0.0, time.monotonic() - started)


def scrape_metrics(url: str, token: str = "", timeout: float = 2) -> str:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        response = httpx.get(url, headers=headers, timeout=timeout, follow_redirects=False)
        response.raise_for_status()
        return response.text if response.text.endswith("\n") else response.text + "\n"
    except httpx.HTTPError:
        return ""

"""Durable, admin-controlled workspace storage capacity orchestration.

The public Amosclaud process never receives a cloud-provider credential and never
runs privileged partition or filesystem commands. It records an auditable resize
job and delegates the operation to an internal storage controller.
"""

from __future__ import annotations

import ipaddress
import json
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx

from amoscloud_ai.api.routes import auth

_TERMINAL_STATES = {"completed", "failed", "cancelled"}
_RUNNING_STATES = {"queued", "running", "snapshotting", "resizing", "expanding"}


class StorageCapacityError(RuntimeError):
    """Raised when the storage controller or capacity policy blocks an operation."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _loads(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def _json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def _connect() -> sqlite3.Connection:
    db = auth._connect()
    db.execute("PRAGMA foreign_keys = ON")
    db.row_factory = sqlite3.Row
    return db


def ensure_schema(db: sqlite3.Connection, *, commit: bool = True) -> None:
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS storage_resize_jobs (
            id TEXT PRIMARY KEY,
            requested_by INTEGER NOT NULL,
            provider TEXT NOT NULL CHECK(provider IN ('gcp','aws')),
            resource_json TEXT NOT NULL,
            target_size_gib INTEGER NOT NULL CHECK(target_size_gib > 0),
            mountpoint TEXT NOT NULL,
            expected_device TEXT,
            snapshot_required INTEGER NOT NULL DEFAULT 1 CHECK(snapshot_required IN (0,1)),
            expand_filesystem INTEGER NOT NULL DEFAULT 1 CHECK(expand_filesystem IN (0,1)),
            dry_run INTEGER NOT NULL DEFAULT 0 CHECK(dry_run IN (0,1)),
            status TEXT NOT NULL,
            controller_operation_id TEXT,
            result_json TEXT NOT NULL DEFAULT '{}',
            error TEXT,
            created_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(requested_by) REFERENCES users(id) ON DELETE RESTRICT
        );
        CREATE INDEX IF NOT EXISTS idx_storage_resize_jobs_created
            ON storage_resize_jobs(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_storage_resize_jobs_status
            ON storage_resize_jobs(status, created_at);

        CREATE TABLE IF NOT EXISTS storage_resize_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            message TEXT NOT NULL,
            details_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            FOREIGN KEY(job_id) REFERENCES storage_resize_jobs(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_storage_resize_events_job
            ON storage_resize_events(job_id, id);
        """
    )
    if commit:
        db.commit()


def add_event(
    db: sqlite3.Connection,
    job_id: str,
    event_type: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> None:
    db.execute(
        """INSERT INTO storage_resize_events(
               job_id,event_type,message,details_json,created_at
           ) VALUES (?,?,?,?,?)""",
        (job_id, event_type, str(message)[:2_000], _json(details or {}), _now()),
    )


def create_job(
    *,
    requested_by: int,
    provider: str,
    resource: dict[str, Any],
    target_size_gib: int,
    mountpoint: str,
    expected_device: str | None,
    snapshot_required: bool,
    expand_filesystem: bool,
    dry_run: bool,
) -> dict[str, Any]:
    job_id = "resize_" + uuid.uuid4().hex
    now = _now()
    with _connect() as db:
        ensure_schema(db, commit=False)
        db.execute(
            """INSERT INTO storage_resize_jobs(
                   id,requested_by,provider,resource_json,target_size_gib,mountpoint,
                   expected_device,snapshot_required,expand_filesystem,dry_run,status,
                   created_at,updated_at
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                job_id,
                requested_by,
                provider,
                _json(resource),
                target_size_gib,
                mountpoint,
                expected_device,
                int(snapshot_required),
                int(expand_filesystem),
                int(dry_run),
                "queued",
                now,
                now,
            ),
        )
        add_event(
            db,
            job_id,
            "job.queued",
            "Storage resize request entered the durable controller queue.",
            {
                "provider": provider,
                "target_size_gib": target_size_gib,
                "snapshot_required": snapshot_required,
                "expand_filesystem": expand_filesystem,
                "dry_run": dry_run,
            },
        )
        db.commit()
        row = db.execute("SELECT * FROM storage_resize_jobs WHERE id=?", (job_id,)).fetchone()
    if not row:
        raise RuntimeError("Storage resize job was not persisted")
    return job_dict(row)


def job_dict(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["resource"] = _loads(item.pop("resource_json"), {})
    item["result"] = _loads(item.pop("result_json"), {})
    for name in ("snapshot_required", "expand_filesystem", "dry_run"):
        item[name] = bool(item[name])
    return item


def get_job(job_id: str) -> dict[str, Any]:
    with _connect() as db:
        ensure_schema(db)
        row = db.execute("SELECT * FROM storage_resize_jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise StorageCapacityError("Storage resize job not found")
        result = job_dict(row)
        result["events"] = [
            {
                "event_type": event["event_type"],
                "message": event["message"],
                "details": _loads(event["details_json"], {}),
                "created_at": event["created_at"],
            }
            for event in db.execute(
                """SELECT event_type,message,details_json,created_at
                   FROM storage_resize_events WHERE job_id=? ORDER BY id""",
                (job_id,),
            ).fetchall()
        ]
    return result


def list_jobs(limit: int = 100) -> list[dict[str, Any]]:
    with _connect() as db:
        ensure_schema(db)
        rows = db.execute(
            "SELECT * FROM storage_resize_jobs ORDER BY created_at DESC LIMIT ?",
            (max(1, min(limit, 500)),),
        ).fetchall()
    return [job_dict(row) for row in rows]


def _controller_url() -> str:
    value = os.getenv("AMOSCLAUD_STORAGE_CONTROLLER_URL", "").strip().rstrip("/")
    if not value:
        raise StorageCapacityError("AMOSCLAUD_STORAGE_CONTROLLER_URL is not configured")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise StorageCapacityError("Storage controller URL is invalid")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise StorageCapacityError("Storage controller URL must not contain credentials or query data")
    if parsed.scheme == "http":
        host = parsed.hostname
        allowed = host in {"localhost", "127.0.0.1", "::1"}
        try:
            allowed = allowed or ipaddress.ip_address(host).is_private
        except ValueError:
            pass
        if not allowed:
            raise StorageCapacityError(
                "Plain HTTP storage controller URLs are allowed only on loopback or private IPs"
            )
    return value


def _controller_token() -> str:
    value = os.getenv("AMOSCLAUD_STORAGE_CONTROLLER_TOKEN", "").strip()
    if len(value) < 32:
        raise StorageCapacityError("AMOSCLAUD_STORAGE_CONTROLLER_TOKEN is missing or too short")
    return value


def controller_health() -> dict[str, Any]:
    try:
        url = _controller_url()
        token = _controller_token()
        response = httpx.get(
            f"{url}/ready",
            headers={"Authorization": f"Bearer {token}"},
            timeout=5,
        )
        response.raise_for_status()
        payload = response.json()
        return {
            "configured": True,
            "reachable": True,
            "detail": payload.get("detail") or "Storage controller is ready.",
            "providers": payload.get("providers", []),
        }
    except Exception as exc:
        return {
            "configured": bool(os.getenv("AMOSCLAUD_STORAGE_CONTROLLER_URL")),
            "reachable": False,
            "detail": f"Storage controller unavailable: {type(exc).__name__}",
            "providers": [],
        }


def _update_job(
    job_id: str,
    *,
    status: str,
    message: str,
    event_type: str,
    result: dict[str, Any] | None = None,
    error: str | None = None,
    controller_operation_id: str | None = None,
    finished: bool = False,
) -> None:
    now = _now()
    with _connect() as db:
        ensure_schema(db, commit=False)
        current = db.execute("SELECT * FROM storage_resize_jobs WHERE id=?", (job_id,)).fetchone()
        if not current:
            return
        started_at = current["started_at"] or (now if status == "running" else None)
        finished_at = now if finished else current["finished_at"]
        db.execute(
            """UPDATE storage_resize_jobs SET
                   status=?,controller_operation_id=COALESCE(?,controller_operation_id),
                   result_json=?,error=?,started_at=COALESCE(started_at,?),
                   finished_at=?,updated_at=? WHERE id=?""",
            (
                status,
                controller_operation_id,
                _json(result or _loads(current["result_json"], {})),
                error,
                started_at,
                finished_at,
                now,
                job_id,
            ),
        )
        add_event(db, job_id, event_type, message, result or {})
        db.commit()


def execute_job(job_id: str) -> None:
    """Send one durable job to the internal privileged storage controller."""

    with _connect() as db:
        ensure_schema(db)
        row = db.execute("SELECT * FROM storage_resize_jobs WHERE id=?", (job_id,)).fetchone()
    if not row:
        return
    job = job_dict(row)
    if job["status"] in _TERMINAL_STATES:
        return

    _update_job(
        job_id,
        status="running",
        message="The internal storage controller accepted the resize workflow.",
        event_type="job.running",
    )
    payload = {
        "request_id": job_id,
        "provider": job["provider"],
        "target_size_gib": job["target_size_gib"],
        "resource": job["resource"],
        "mountpoint": job["mountpoint"],
        "expected_device": job["expected_device"],
        "snapshot_required": job["snapshot_required"],
        "expand_filesystem": job["expand_filesystem"],
        "dry_run": job["dry_run"],
    }
    try:
        timeout = max(60, min(int(os.getenv("AMOSCLAUD_STORAGE_RESIZE_TIMEOUT_SECONDS", "7200")), 21600))
        response = httpx.post(
            f"{_controller_url()}/v1/resize",
            headers={"Authorization": f"Bearer {_controller_token()}"},
            json=payload,
            timeout=timeout,
        )
        response.raise_for_status()
        result = response.json()
        _update_job(
            job_id,
            status="completed",
            message="Cloud disk and filesystem resize completed and was verified.",
            event_type="job.completed",
            result=result,
            controller_operation_id=str(result.get("operation_id") or "") or None,
            finished=True,
        )
    except Exception as exc:
        detail = str(exc)
        if isinstance(exc, httpx.HTTPStatusError):
            try:
                body = exc.response.json()
                detail = str(body.get("detail") or detail)
            except ValueError:
                detail = exc.response.text[:1_000] or detail
        _update_job(
            job_id,
            status="failed",
            message="Storage resize stopped safely before reporting success.",
            event_type="job.failed",
            error=f"{type(exc).__name__}: {detail}"[:2_000],
            result={"failure_type": type(exc).__name__},
            finished=True,
        )


def dispatch_job(job_id: str) -> None:
    try:
        from amoscloud_ai.task_dispatch import dispatch_task
        from amoscloud_ai.worker import run_storage_resize

        dispatch_task(run_storage_resize, job_id)
    except Exception:
        if os.getenv("ENVIRONMENT", "development").strip().lower() == "production":
            raise
        thread = threading.Thread(
            target=execute_job,
            args=(job_id,),
            name=f"amosclaud-storage-{job_id[-8:]}",
            daemon=True,
        )
        thread.start()


def recover_jobs() -> int:
    """Return interrupted jobs to the queue after a worker restart."""

    recovered = 0
    with _connect() as db:
        ensure_schema(db, commit=False)
        rows = db.execute(
            """SELECT id,status FROM storage_resize_jobs
               WHERE status IN ('queued','running','snapshotting','resizing','expanding')
               ORDER BY created_at"""
        ).fetchall()
        for row in rows:
            db.execute(
                "UPDATE storage_resize_jobs SET status='queued',updated_at=? WHERE id=?",
                (_now(), row["id"]),
            )
            add_event(
                db,
                row["id"],
                "job.recovered",
                "Storage resize job was recovered after a worker restart.",
                {"previous_status": row["status"]},
            )
            recovered += 1
        db.commit()
    for row in rows:
        dispatch_job(str(row["id"]))
    return recovered

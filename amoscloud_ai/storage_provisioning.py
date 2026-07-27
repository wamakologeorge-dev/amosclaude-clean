"""Durable orchestration for new Amosclaud workspace volumes.

The public API persists an administrator-approved provisioning request and sends
it to the private storage controller. Cloud credentials and privileged block
commands remain outside the public process and developer workspaces.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx

from amoscloud_ai import storage_capacity
from amoscloud_ai.api.routes import auth

_TERMINAL_STATES = {
    "completed",
    "failed",
    "cancelled",
    "operator_review_required",
}
_ACTIVE_STATES = {
    "running",
    "creating",
    "attaching",
    "formatting",
    "mounting",
    "validating",
}


class StorageProvisioningError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def _loads(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def _connect() -> sqlite3.Connection:
    db = auth._connect()
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def ensure_schema(db: sqlite3.Connection, *, commit: bool = True) -> None:
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS storage_provision_jobs (
            id TEXT PRIMARY KEY,
            requested_by INTEGER NOT NULL,
            provider TEXT NOT NULL CHECK(provider IN ('gcp','aws')),
            resource_json TEXT NOT NULL,
            size_gib INTEGER NOT NULL CHECK(size_gib BETWEEN 10 AND 65536),
            mountpoint TEXT NOT NULL,
            filesystem TEXT NOT NULL CHECK(filesystem IN ('ext4','xfs')),
            filesystem_label TEXT NOT NULL,
            owner_uid INTEGER NOT NULL,
            owner_gid INTEGER NOT NULL,
            directory_mode TEXT NOT NULL,
            persist_mount INTEGER NOT NULL DEFAULT 0 CHECK(persist_mount IN (0,1)),
            benchmark_size_gib INTEGER NOT NULL DEFAULT 10
                CHECK(benchmark_size_gib BETWEEN 0 AND 100),
            confirmation TEXT NOT NULL,
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
        CREATE INDEX IF NOT EXISTS idx_storage_provision_jobs_created
            ON storage_provision_jobs(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_storage_provision_jobs_status
            ON storage_provision_jobs(status,created_at);

        CREATE TABLE IF NOT EXISTS storage_provision_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            message TEXT NOT NULL,
            details_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            FOREIGN KEY(job_id) REFERENCES storage_provision_jobs(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_storage_provision_events_job
            ON storage_provision_events(job_id,id);
        """
    )
    if commit:
        db.commit()


def _event(
    db: sqlite3.Connection,
    job_id: str,
    event_type: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> None:
    db.execute(
        """INSERT INTO storage_provision_events(
               job_id,event_type,message,details_json,created_at
           ) VALUES (?,?,?,?,?)""",
        (job_id, event_type, message[:2_000], _json(details or {}), _now()),
    )


def create_job(
    *,
    requested_by: int,
    provider: str,
    resource: dict[str, Any],
    size_gib: int,
    mountpoint: str,
    filesystem: str,
    filesystem_label: str,
    owner_uid: int,
    owner_gid: int,
    directory_mode: str,
    persist_mount: bool,
    benchmark_size_gib: int,
    confirmation: str,
    dry_run: bool,
) -> dict[str, Any]:
    job_id = "provision_" + uuid.uuid4().hex
    now = _now()
    with _connect() as db:
        ensure_schema(db, commit=False)
        db.execute(
            """INSERT INTO storage_provision_jobs(
                   id,requested_by,provider,resource_json,size_gib,mountpoint,
                   filesystem,filesystem_label,owner_uid,owner_gid,directory_mode,
                   persist_mount,benchmark_size_gib,confirmation,dry_run,status,
                   created_at,updated_at
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                job_id,
                requested_by,
                provider,
                _json(resource),
                size_gib,
                mountpoint,
                filesystem,
                filesystem_label,
                owner_uid,
                owner_gid,
                directory_mode,
                int(persist_mount),
                benchmark_size_gib,
                confirmation,
                int(dry_run),
                "queued",
                now,
                now,
            ),
        )
        _event(
            db,
            job_id,
            "job.queued",
            "New workspace volume request entered the durable storage queue.",
            {
                "provider": provider,
                "size_gib": size_gib,
                "filesystem": filesystem,
                "benchmark_size_gib": benchmark_size_gib,
                "dry_run": dry_run,
            },
        )
        db.commit()
        row = db.execute(
            "SELECT * FROM storage_provision_jobs WHERE id=?",
            (job_id,),
        ).fetchone()
    if not row:
        raise RuntimeError("Storage provisioning job was not persisted")
    return job_dict(row)


def job_dict(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["resource"] = _loads(item.pop("resource_json"), {})
    item["result"] = _loads(item.pop("result_json"), {})
    for name in ("persist_mount", "dry_run"):
        item[name] = bool(item[name])
    # The exact confirmation is an authorization phrase, not useful response data.
    item.pop("confirmation", None)
    return item


def get_job(job_id: str) -> dict[str, Any]:
    with _connect() as db:
        ensure_schema(db)
        row = db.execute(
            "SELECT * FROM storage_provision_jobs WHERE id=?",
            (job_id,),
        ).fetchone()
        if not row:
            raise StorageProvisioningError("Storage provisioning job not found")
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
                   FROM storage_provision_events WHERE job_id=? ORDER BY id""",
                (job_id,),
            ).fetchall()
        ]
        return result


def list_jobs(limit: int = 100) -> list[dict[str, Any]]:
    with _connect() as db:
        ensure_schema(db)
        rows = db.execute(
            """SELECT * FROM storage_provision_jobs
               ORDER BY created_at DESC LIMIT ?""",
            (max(1, min(limit, 500)),),
        ).fetchall()
    return [job_dict(row) for row in rows]


def _update(
    job_id: str,
    *,
    status: str,
    event_type: str,
    message: str,
    result: dict[str, Any] | None = None,
    error: str | None = None,
    controller_operation_id: str | None = None,
    finished: bool = False,
) -> None:
    now = _now()
    with _connect() as db:
        ensure_schema(db, commit=False)
        row = db.execute(
            "SELECT * FROM storage_provision_jobs WHERE id=?",
            (job_id,),
        ).fetchone()
        if not row:
            return
        started_at = row["started_at"] or (now if status == "running" else None)
        finished_at = now if finished else row["finished_at"]
        db.execute(
            """UPDATE storage_provision_jobs SET
                   status=?,controller_operation_id=COALESCE(?,controller_operation_id),
                   result_json=?,error=?,started_at=COALESCE(started_at,?),
                   finished_at=?,updated_at=? WHERE id=?""",
            (
                status,
                controller_operation_id,
                _json(result or _loads(row["result_json"], {})),
                error,
                started_at,
                finished_at,
                now,
                job_id,
            ),
        )
        _event(db, job_id, event_type, message, result or {})
        db.commit()


def execute_job(job_id: str) -> None:
    with _connect() as db:
        ensure_schema(db)
        row = db.execute(
            "SELECT * FROM storage_provision_jobs WHERE id=?",
            (job_id,),
        ).fetchone()
    if not row:
        return
    status = str(row["status"])
    if status in _TERMINAL_STATES:
        return
    if status != "queued":
        # Provisioning includes non-idempotent host formatting. A duplicate worker
        # must never replay an active or interrupted job.
        return

    _update(
        job_id,
        status="running",
        event_type="job.running",
        message="The private storage controller accepted the provisioning workflow.",
    )
    payload = {
        "request_id": job_id,
        "provider": row["provider"],
        "size_gib": int(row["size_gib"]),
        "resource": _loads(row["resource_json"], {}),
        "mountpoint": row["mountpoint"],
        "filesystem": row["filesystem"],
        "filesystem_label": row["filesystem_label"],
        "owner_uid": int(row["owner_uid"]),
        "owner_gid": int(row["owner_gid"]),
        "directory_mode": row["directory_mode"],
        "persist_mount": bool(row["persist_mount"]),
        "benchmark_size_gib": int(row["benchmark_size_gib"]),
        "confirmation": row["confirmation"],
        "dry_run": bool(row["dry_run"]),
    }
    try:
        timeout = max(
            600,
            min(
                int(
                    os.getenv(
                        "AMOSCLAUD_STORAGE_PROVISION_TIMEOUT_SECONDS",
                        "21600",
                    )
                ),
                43200,
            ),
        )
        response = httpx.post(
            f"{storage_capacity._controller_url()}/v1/provision",
            headers={
                "Authorization": f"Bearer {storage_capacity._controller_token()}"
            },
            json=payload,
            timeout=timeout,
        )
        response.raise_for_status()
        result = response.json()
        if not bool(result.get("verified")):
            raise StorageProvisioningError(
                "Storage controller returned without verified provisioning evidence"
            )
        _update(
            job_id,
            status="completed",
            event_type="job.completed",
            message=(
                "Cloud volume creation, attachment, filesystem preparation, "
                "mounting, and validation completed."
            ),
            result=result,
            controller_operation_id=str(result.get("operation_id") or "") or None,
            finished=True,
        )
    except Exception as exc:
        detail = str(exc)
        if isinstance(exc, httpx.HTTPStatusError):
            try:
                detail = str(exc.response.json().get("detail") or detail)
            except ValueError:
                detail = exc.response.text[:1_000] or detail
        _update(
            job_id,
            status="failed",
            event_type="job.failed",
            message="Volume provisioning stopped safely before reporting success.",
            error=f"{type(exc).__name__}: {detail}"[:2_000],
            result={"failure_type": type(exc).__name__},
            finished=True,
        )


def dispatch_job(job_id: str) -> None:
    try:
        from amoscloud_ai.task_dispatch import dispatch_task
        from amoscloud_ai.worker import run_storage_provision

        dispatch_task(run_storage_provision, job_id)
    except Exception:
        if os.getenv("ENVIRONMENT", "development").strip().lower() == "production":
            raise
        thread = threading.Thread(
            target=execute_job,
            args=(job_id,),
            name=f"amosclaud-provision-{job_id[-8:]}",
            daemon=True,
        )
        thread.start()


def recover_jobs() -> int:
    """Recover queued work but never replay interrupted formatting operations."""

    queued_ids: list[str] = []
    interrupted = 0
    with _connect() as db:
        ensure_schema(db, commit=False)
        queued = db.execute(
            """SELECT id FROM storage_provision_jobs
               WHERE status='queued' ORDER BY created_at"""
        ).fetchall()
        queued_ids = [str(row["id"]) for row in queued]

        placeholders = ",".join("?" for _ in _ACTIVE_STATES)
        active = db.execute(
            f"""SELECT id,status FROM storage_provision_jobs
                WHERE status IN ({placeholders}) ORDER BY created_at""",
            tuple(sorted(_ACTIVE_STATES)),
        ).fetchall()
        for row in active:
            db.execute(
                """UPDATE storage_provision_jobs
                   SET status='operator_review_required',
                       error=?,finished_at=?,updated_at=? WHERE id=?""",
                (
                    (
                        "Worker restart interrupted a non-idempotent provisioning "
                        "operation. Inspect the cloud volume and host device before "
                        "creating any replacement job."
                    ),
                    _now(),
                    _now(),
                    row["id"],
                ),
            )
            _event(
                db,
                row["id"],
                "job.operator_review_required",
                (
                    "Provisioning was interrupted and was not replayed because cloud "
                    "attachment and filesystem formatting are not safe to repeat blindly."
                ),
                {"previous_status": row["status"]},
            )
            interrupted += 1
        db.commit()

    for job_id in queued_ids:
        dispatch_job(job_id)
    return len(queued_ids) + interrupted

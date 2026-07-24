"""Server Station management for self-hosted Amosclaud execution nodes."""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Cookie, Header, HTTPException

from amoscloud_ai.api.routes.auth import _connect, get_user_from_session
from amoscloud_ai.api.routes.task_router import (
    RunnerCreate,
    RunnerHeartbeat,
    _ensure_schema,
    _hash,
    _json,
    _loads,
    _now,
    _runner_auth,
    claim_task,
)

router = APIRouter(prefix="/server-stations", tags=["server-stations"])
ONLINE_WINDOW = timedelta(seconds=90)


def _user(token: str | None):
    user = get_user_from_session(token)
    if not user:
        raise HTTPException(status_code=401, detail="Sign in to manage Server Stations")
    return user


def _effective_status(row) -> str:
    if row["revoked_at"]:
        return "revoked"
    if row["status"] == "busy":
        return "busy"
    if not row["last_seen_at"]:
        return "offline"
    try:
        seen = datetime.fromisoformat(row["last_seen_at"])
    except ValueError:
        return "offline"
    return "online" if datetime.now(timezone.utc) - seen <= ONLINE_WINDOW else "offline"


def _station(db, row) -> dict:
    work = db.execute(
        """SELECT
             SUM(CASE WHEN status='queued' THEN 1 ELSE 0 END) AS queued,
             SUM(CASE WHEN status='running' THEN 1 ELSE 0 END) AS running,
             SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) AS completed,
             SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed
           FROM global_tasks WHERE runner_id=?""",
        (row["id"],),
    ).fetchone()
    return {
        "id": row["id"],
        "name": row["name"],
        "status": _effective_status(row),
        "version": row["version"],
        "capabilities": _loads(row["capabilities_json"], []),
        "labels": _loads(row["labels_json"], []),
        "system": _loads(row["system_json"], {}),
        "created_at": row["created_at"],
        "last_seen_at": row["last_seen_at"],
        "revoked_at": row["revoked_at"],
        "work": {key: int(work[key] or 0) for key in ("queued", "running", "completed", "failed")},
    }


@router.post("", status_code=201)
def create_station(
    body: RunnerCreate,
    amos_session: str | None = Cookie(default=None),
) -> dict:
    user = _user(amos_session)
    station_id = "station_" + uuid.uuid4().hex
    token = "amos_station_" + secrets.token_urlsafe(36)
    with _connect() as db:
        _ensure_schema(db)
        db.execute(
            """INSERT INTO task_runners
               (id,user_id,name,token_hash,token_prefix,capabilities_json,labels_json,status,created_at)
               VALUES (?,?,?,?,?,?,?,'offline',?)""",
            (
                station_id,
                user["id"],
                body.name.strip(),
                _hash(token),
                token[:21],
                _json(sorted(set(body.capabilities))),
                _json(sorted(set(body.labels))),
                _now(),
            ),
        )
        db.commit()
    return {
        "id": station_id,
        "name": body.name.strip(),
        "station_token": token,
        "next": "Install the Amosclaud service on the station and configure this credential.",
        "warning": "Copy this credential now. Amosclaud stores only its hash.",
    }


@router.get("")
def list_stations(amos_session: str | None = Cookie(default=None)) -> list[dict]:
    user = _user(amos_session)
    with _connect() as db:
        _ensure_schema(db)
        rows = db.execute(
            "SELECT * FROM task_runners WHERE user_id=? ORDER BY created_at DESC",
            (user["id"],),
        ).fetchall()
        return [_station(db, row) for row in rows]


@router.get("/{station_id}")
def get_station(station_id: str, amos_session: str | None = Cookie(default=None)) -> dict:
    user = _user(amos_session)
    with _connect() as db:
        _ensure_schema(db)
        row = db.execute(
            "SELECT * FROM task_runners WHERE id=? AND user_id=?",
            (station_id, user["id"]),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Server Station not found")
        return _station(db, row)


@router.post("/{station_id}/heartbeat")
def station_heartbeat(
    station_id: str,
    body: RunnerHeartbeat,
    authorization: str | None = Header(default=None),
) -> dict:
    with _connect() as db:
        _ensure_schema(db)
        station = _runner_auth(db, station_id, authorization)
        capabilities = body.capabilities or _loads(station["capabilities_json"], [])
        db.execute(
            """UPDATE task_runners
               SET status='online',version=?,capabilities_json=?,system_json=?,last_seen_at=?
               WHERE id=?""",
            (body.version, _json(capabilities), _json(body.system), _now(), station_id),
        )
        db.commit()
    return {"ok": True, "station_id": station_id, "status": "online"}


@router.post("/{station_id}/claim")
def station_claim(
    station_id: str,
    authorization: str | None = Header(default=None),
) -> dict | None:
    return claim_task(station_id, authorization)


@router.post("/{station_id}/rotate-token")
def rotate_station_token(
    station_id: str,
    amos_session: str | None = Cookie(default=None),
) -> dict:
    user = _user(amos_session)
    token = "amos_station_" + secrets.token_urlsafe(36)
    with _connect() as db:
        _ensure_schema(db)
        cursor = db.execute(
            """UPDATE task_runners SET token_hash=?,token_prefix=?,revoked_at=NULL,status='offline'
               WHERE id=? AND user_id=?""",
            (_hash(token), token[:21], station_id, user["id"]),
        )
        db.commit()
    if cursor.rowcount != 1:
        raise HTTPException(status_code=404, detail="Server Station not found")
    return {
        "id": station_id,
        "station_token": token,
        "warning": "The previous credential is invalid. Copy this credential now.",
    }


@router.delete("/{station_id}", status_code=204)
def revoke_station(station_id: str, amos_session: str | None = Cookie(default=None)) -> None:
    user = _user(amos_session)
    with _connect() as db:
        _ensure_schema(db)
        cursor = db.execute(
            """UPDATE task_runners SET revoked_at=?,status='offline'
               WHERE id=? AND user_id=? AND revoked_at IS NULL""",
            (_now(), station_id, user["id"]),
        )
        db.execute(
            """UPDATE global_tasks SET runner_id=NULL
               WHERE runner_id=? AND status IN ('queued','awaiting_approval')""",
            (station_id,),
        )
        db.commit()
    if cursor.rowcount != 1:
        raise HTTPException(status_code=404, detail="Active Server Station not found")

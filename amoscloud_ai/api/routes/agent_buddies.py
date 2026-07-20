"""Truthful heartbeat and status API for Amosclaud Agent Buddies."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from amoscloud_ai.api.routes import auth
from amoscloud_ai.api.routes.agent_readiness import _connector_user

router = APIRouter(prefix="/agent/buddies", tags=["agent-buddies"])
_BUDDY_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")

DEFAULT_BUDDIES = (
    ("receiver", "Request Receiver", "understand and normalize developer requests"),
    ("researcher", "Evidence Researcher", "inspect repositories and runtime evidence"),
    ("planner", "Solution Planner", "design bounded implementation plans"),
    ("builder", "Software Builder", "apply authorized workspace changes"),
    ("verifier", "Result Verifier", "run checks and report evidence"),
)


class BuddyHeartbeat(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    role: str = Field(min_length=2, max_length=200)
    status: Literal["idle", "working", "blocked", "draining"] = "idle"
    capabilities: list[str] = Field(default_factory=list, max_length=50)
    active_tasks: int = Field(default=0, ge=0, le=10000)
    capacity: int = Field(default=1, ge=1, le=10000)
    version: str = Field(default="1.0.0", min_length=1, max_length=40)
    detail: str = Field(default="", max_length=300)


def _schema() -> None:
    with auth._connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS agent_buddy_heartbeats (
          owner_user_id INTEGER NOT NULL,
          buddy_id TEXT NOT NULL,
          name TEXT NOT NULL,
          role TEXT NOT NULL,
          reported_status TEXT NOT NULL,
          capabilities_json TEXT NOT NULL,
          active_tasks INTEGER NOT NULL,
          capacity INTEGER NOT NULL,
          version TEXT NOT NULL,
          detail TEXT NOT NULL,
          last_heartbeat_at TEXT NOT NULL,
          PRIMARY KEY(owner_user_id,buddy_id)
        );
        CREATE INDEX IF NOT EXISTS idx_agent_buddy_heartbeat
          ON agent_buddy_heartbeats(owner_user_id,last_heartbeat_at);
        """)
        db.commit()


def _credential(authorization: str | None, x_api_key: str | None) -> tuple[str | None, str | None]:
    return authorization, x_api_key


def _authorized_owner(
    request: Request,
    authorization: str | None,
    x_api_key: str | None,
) -> dict[str, Any]:
    user = auth.get_user_from_session(request.cookies.get("amos_session"))
    if user:
        return dict(user)
    header, key = _credential(authorization, x_api_key)
    return _connector_user(header, key)


def _online_seconds() -> int:
    try:
        value = int(os.getenv("AMOSCLAUD_BUDDY_ONLINE_SECONDS", "90"))
    except ValueError as exc:
        raise HTTPException(status_code=503, detail="Buddy heartbeat window is invalid") from exc
    return max(10, min(value, 3600))


def _age_seconds(value: str, now: datetime) -> float:
    try:
        observed = datetime.fromisoformat(value)
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=timezone.utc)
        return max(0.0, (now - observed.astimezone(timezone.utc)).total_seconds())
    except (TypeError, ValueError):
        return float("inf")


def _presence(age: float, reported: str, online_window: int) -> str:
    if age <= online_window:
        return "blocked" if reported == "blocked" else "online"
    if age <= online_window * 3:
        return "stale"
    return "offline"


def _buddy_payload(row: Any, now: datetime, online_window: int) -> dict[str, Any]:
    age = _age_seconds(row["last_heartbeat_at"], now)
    presence = _presence(age, row["reported_status"], online_window)
    return {
        "buddy_id": row["buddy_id"],
        "name": row["name"],
        "role": row["role"],
        "presence": presence,
        "reported_status": row["reported_status"],
        "responding": presence in {"online", "blocked"},
        "capabilities": json.loads(row["capabilities_json"]),
        "active_tasks": row["active_tasks"],
        "capacity": row["capacity"],
        "available_slots": max(0, row["capacity"] - row["active_tasks"]),
        "version": row["version"],
        "detail": row["detail"],
        "last_heartbeat_at": row["last_heartbeat_at"],
        "heartbeat_age_seconds": None if age == float("inf") else round(age, 3),
    }


def _unregistered_buddy(buddy_id: str, name: str, role: str) -> dict[str, Any]:
    return {
        "buddy_id": buddy_id,
        "name": name,
        "role": role,
        "presence": "offline",
        "reported_status": "unregistered",
        "responding": False,
        "capabilities": [],
        "active_tasks": 0,
        "capacity": 0,
        "available_slots": 0,
        "version": None,
        "detail": "No heartbeat has been received.",
        "last_heartbeat_at": None,
        "heartbeat_age_seconds": None,
    }


@router.get("/health")
def buddies_health() -> dict[str, Any]:
    _schema()
    return {
        "status": "ok",
        "service": "amosclaud-agent-buddies-api",
        "heartbeat_window_seconds": _online_seconds(),
    }


@router.post("/{buddy_id}/heartbeat")
def buddy_heartbeat(
    buddy_id: str,
    body: BuddyHeartbeat,
    request: Request,
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    if not _BUDDY_ID.fullmatch(buddy_id):
        raise HTTPException(status_code=422, detail="Invalid buddy identifier")
    owner = _authorized_owner(request, authorization, x_api_key)
    _schema()
    now = datetime.now(timezone.utc).isoformat()
    capabilities = sorted({item.strip() for item in body.capabilities if item.strip()})
    with auth._connect() as db:
        db.execute(
            """INSERT INTO agent_buddy_heartbeats(
                 owner_user_id,buddy_id,name,role,reported_status,capabilities_json,
                 active_tasks,capacity,version,detail,last_heartbeat_at
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(owner_user_id,buddy_id) DO UPDATE SET
                 name=excluded.name,role=excluded.role,reported_status=excluded.reported_status,
                 capabilities_json=excluded.capabilities_json,active_tasks=excluded.active_tasks,
                 capacity=excluded.capacity,version=excluded.version,detail=excluded.detail,
                 last_heartbeat_at=excluded.last_heartbeat_at""",
            (
                owner["id"],
                buddy_id,
                body.name.strip(),
                body.role.strip(),
                body.status,
                json.dumps(capabilities),
                body.active_tasks,
                body.capacity,
                body.version.strip(),
                body.detail.strip(),
                now,
            ),
        )
        db.commit()
        row = db.execute(
            "SELECT * FROM agent_buddy_heartbeats WHERE owner_user_id=? AND buddy_id=?",
            (owner["id"], buddy_id),
        ).fetchone()
    return _buddy_payload(row, datetime.now(timezone.utc), _online_seconds())


def _status_response(owner_id: int) -> dict[str, Any]:
    _schema()
    now = datetime.now(timezone.utc)
    window = _online_seconds()
    with auth._connect() as db:
        rows = db.execute(
            "SELECT * FROM agent_buddy_heartbeats WHERE owner_user_id=? ORDER BY buddy_id",
            (owner_id,),
        ).fetchall()
    by_id = {row["buddy_id"]: row for row in rows}
    buddies = []
    known_ids = set()
    for buddy_id, name, role in DEFAULT_BUDDIES:
        known_ids.add(buddy_id)
        row = by_id.get(buddy_id)
        buddies.append(
            _buddy_payload(row, now, window) if row else _unregistered_buddy(buddy_id, name, role)
        )
    for buddy_id in sorted(set(by_id) - known_ids):
        buddies.append(_buddy_payload(by_id[buddy_id], now, window))
    online = sum(item["responding"] for item in buddies)
    blocked = sum(item["presence"] == "blocked" for item in buddies)
    team_status = "offline" if online == 0 else "ready" if online == len(buddies) else "degraded"
    return {
        "status": "ok",
        "service": "amosclaud-agent-buddies-api",
        "team_status": team_status,
        "responding": online > 0,
        "generated_at": now.isoformat(),
        "heartbeat_window_seconds": window,
        "summary": {
            "total": len(buddies),
            "online": online,
            "blocked": blocked,
            "offline_or_stale": len(buddies) - online,
        },
        "buddies": buddies,
    }


@router.get("/status")
def buddies_status(
    request: Request,
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    owner = _authorized_owner(request, authorization, x_api_key)
    return _status_response(int(owner["id"]))


@router.get("/status/respond")
def buddies_status_respond(
    request: Request,
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    """Compatibility response endpoint for simple server monitors."""
    owner = _authorized_owner(request, authorization, x_api_key)
    result = _status_response(int(owner["id"]))
    return {
        "responding": result["responding"],
        "team_status": result["team_status"],
        "online_buddies": result["summary"]["online"],
        "total_buddies": result["summary"]["total"],
        "status_url": "/api/v1/agent/buddies/status",
    }

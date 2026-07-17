from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from amoscloud_ai.api.routes.core import _owner_user

router = APIRouter(prefix="/autonomous", tags=["autonomous-state"])


def _db_path() -> Path:
    return Path(os.getenv("AUTONOMOUS_STATE_DB", "/data/autonomous-state.db"))


def _connect() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS autonomous_sessions (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            active_objective TEXT,
            repository_id TEXT,
            status TEXT NOT NULL DEFAULT 'chatting',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS autonomous_messages (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(session_id) REFERENCES autonomous_sessions(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS autonomous_results (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            result_type TEXT NOT NULL,
            title TEXT NOT NULL,
            status TEXT NOT NULL,
            summary TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(session_id) REFERENCES autonomous_sessions(id) ON DELETE CASCADE
        );
        """
    )
    db.commit()
    return db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class MessageWrite(BaseModel):
    session_id: str | None = None
    content: str = Field(min_length=1, max_length=20000)
    repository_id: str | None = Field(default=None, max_length=200)


class SessionPatch(BaseModel):
    active_objective: str | None = Field(default=None, max_length=20000)
    repository_id: str | None = Field(default=None, max_length=200)
    status: str | None = Field(default=None, max_length=40)


class ResultWrite(BaseModel):
    session_id: str
    result_type: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=200)
    status: str = Field(min_length=1, max_length=40)
    summary: str = Field(min_length=1, max_length=4000)
    payload: dict = Field(default_factory=dict)


def _session_row(db: sqlite3.Connection, session_id: str, user_id: int):
    row = db.execute(
        "SELECT * FROM autonomous_sessions WHERE id=? AND user_id=?",
        (session_id, user_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Autonomous session not found")
    return row


@router.post("/messages")
def save_message(body: MessageWrite, owner=Depends(_owner_user)) -> dict:
    user_id = int(owner["id"])
    now = _now()
    with _connect() as db:
        session_id = body.session_id or uuid.uuid4().hex
        if body.session_id:
            _session_row(db, session_id, user_id)
            db.execute(
                "UPDATE autonomous_sessions SET repository_id=COALESCE(?,repository_id),updated_at=? WHERE id=?",
                (body.repository_id, now, session_id),
            )
        else:
            db.execute(
                "INSERT INTO autonomous_sessions(id,user_id,title,repository_id,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                (session_id, user_id, body.content[:120], body.repository_id, now, now),
            )
        message_id = uuid.uuid4().hex
        db.execute(
            "INSERT INTO autonomous_messages(id,session_id,role,content,created_at) VALUES(?,?,?,?,?)",
            (message_id, session_id, "user", body.content, now),
        )
        db.commit()
    return {"session_id": session_id, "message_id": message_id, "stored": True}


@router.patch("/sessions/{session_id}")
def update_session(session_id: str, body: SessionPatch, owner=Depends(_owner_user)) -> dict:
    user_id = int(owner["id"])
    with _connect() as db:
        row = _session_row(db, session_id, user_id)
        objective = body.active_objective if body.active_objective is not None else row["active_objective"]
        repository_id = body.repository_id if body.repository_id is not None else row["repository_id"]
        status = body.status if body.status is not None else row["status"]
        db.execute(
            "UPDATE autonomous_sessions SET active_objective=?,repository_id=?,status=?,updated_at=? WHERE id=?",
            (objective, repository_id, status, _now(), session_id),
        )
        db.commit()
    return {"session_id": session_id, "active_objective": objective, "repository_id": repository_id, "status": status}


@router.get("/sessions/current")
def current_session(owner=Depends(_owner_user)) -> dict:
    user_id = int(owner["id"])
    with _connect() as db:
        session = db.execute(
            "SELECT * FROM autonomous_sessions WHERE user_id=? ORDER BY updated_at DESC LIMIT 1",
            (user_id,),
        ).fetchone()
        if session is None:
            return {"session": None, "messages": [], "results": []}
        messages = db.execute(
            "SELECT role,content,created_at FROM autonomous_messages WHERE session_id=? ORDER BY created_at",
            (session["id"],),
        ).fetchall()
        results = db.execute(
            "SELECT * FROM autonomous_results WHERE session_id=? ORDER BY created_at DESC",
            (session["id"],),
        ).fetchall()
    return {
        "session": dict(session),
        "messages": [dict(row) for row in messages],
        "results": [{**dict(row), "payload": json.loads(row["payload_json"])} for row in results],
    }


@router.post("/results")
def save_result(body: ResultWrite, owner=Depends(_owner_user)) -> dict:
    user_id = int(owner["id"])
    now = _now()
    result_id = uuid.uuid4().hex
    with _connect() as db:
        _session_row(db, body.session_id, user_id)
        db.execute(
            "INSERT INTO autonomous_results(id,session_id,user_id,result_type,title,status,summary,payload_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (result_id, body.session_id, user_id, body.result_type, body.title, body.status, body.summary, json.dumps(body.payload), now, now),
        )
        db.execute(
            "UPDATE autonomous_sessions SET status=?,updated_at=? WHERE id=?",
            (body.status, now, body.session_id),
        )
        db.commit()
    return {"result_id": result_id, "stored": True}


@router.get("/results")
def recent_results(limit: int = Query(default=20, ge=1, le=100), owner=Depends(_owner_user)) -> list[dict]:
    user_id = int(owner["id"])
    with _connect() as db:
        rows = db.execute(
            "SELECT * FROM autonomous_results WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
    return [{**dict(row), "payload": json.loads(row["payload_json"])} for row in rows]


@router.get("/results/{result_id}")
def get_result(result_id: str, owner=Depends(_owner_user)) -> dict:
    user_id = int(owner["id"])
    with _connect() as db:
        row = db.execute(
            "SELECT * FROM autonomous_results WHERE id=? AND user_id=?",
            (result_id, user_id),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Autonomous result not found")
    return {**dict(row), "payload": json.loads(row["payload_json"])}


@router.get("/dashboard")
def dashboard(owner=Depends(_owner_user)) -> dict:
    user_id = int(owner["id"])
    with _connect() as db:
        totals = db.execute(
            "SELECT COUNT(*) AS total, SUM(CASE WHEN status IN ('success','completed','verified') THEN 1 ELSE 0 END) AS successful FROM autonomous_results WHERE user_id=?",
            (user_id,),
        ).fetchone()
        recent = db.execute(
            "SELECT id,title,status,result_type,created_at FROM autonomous_results WHERE user_id=? ORDER BY created_at DESC LIMIT 8",
            (user_id,),
        ).fetchall()
        active = db.execute(
            "SELECT id,title,active_objective,repository_id,status,updated_at FROM autonomous_sessions WHERE user_id=? ORDER BY updated_at DESC LIMIT 1",
            (user_id,),
        ).fetchone()
    total = int(totals["total"] or 0)
    successful = int(totals["successful"] or 0)
    return {
        "total_results": total,
        "successful_results": successful,
        "success_rate": round((successful / total) * 100, 1) if total else 0.0,
        "active_session": dict(active) if active else None,
        "recent_results": [dict(row) for row in recent],
    }

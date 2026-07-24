"""Amosclaud-native editable user profile API."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from fastapi import APIRouter, Cookie, HTTPException
from pydantic import BaseModel, Field

from amoscloud_ai.api.routes.auth import DB_PATH, get_user_from_session

router = APIRouter(prefix="/profile", tags=["profile"])


class ProfileUpdate(BaseModel):
    name: str = Field(min_length=2, max_length=100)


def _connect() -> sqlite3.Connection:
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.execute(
        """CREATE TABLE IF NOT EXISTS user_profiles (
            user_id INTEGER PRIMARY KEY,
            bio TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )"""
    )
    db.commit()
    return db


def _current(amos_session: str | None) -> sqlite3.Row:
    user = get_user_from_session(amos_session)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


@router.get("/me")
def read_profile(amos_session: str | None = Cookie(default=None)) -> dict:
    user = _current(amos_session)
    with _connect() as db:
        profile = db.execute(
            "SELECT bio,updated_at FROM user_profiles WHERE user_id=?",
            (user["id"],),
        ).fetchone()
    return {
        "id": int(user["id"]),
        "name": user["name"],
        "email": user["email"],
        "is_admin": bool(user["is_admin"]),
        "provider": user["provider"],
        "bio": profile["bio"] if profile else "",
        "updated_at": profile["updated_at"] if profile else None,
        "repository_platform": "amosclaud-native",
    }


@router.patch("/me")
def update_profile(
    body: ProfileUpdate,
    amos_session: str | None = Cookie(default=None),
) -> dict:
    user = _current(amos_session)
    name = body.name.strip()
    if len(name) < 2:
        raise HTTPException(status_code=422, detail="Profile name is too short")
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as db:
        db.execute("UPDATE users SET name=? WHERE id=?", (name, user["id"]))
        db.execute(
            """INSERT INTO user_profiles(user_id,bio,updated_at) VALUES (?,?,?)
               ON CONFLICT(user_id) DO UPDATE SET updated_at=excluded.updated_at""",
            (user["id"], "", now),
        )
        db.commit()
        updated = db.execute(
            "SELECT id,name,email,is_admin,provider FROM users WHERE id=?",
            (user["id"],),
        ).fetchone()
    return {
        "id": int(updated["id"]),
        "name": updated["name"],
        "email": updated["email"],
        "is_admin": bool(updated["is_admin"]),
        "provider": updated["provider"],
        "updated_at": now,
        "repository_platform": "amosclaud-native",
    }

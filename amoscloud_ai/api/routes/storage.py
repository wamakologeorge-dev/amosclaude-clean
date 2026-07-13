"""Persistent Amosclaud Storage for administrators and developer accounts."""

from __future__ import annotations

import hashlib
import mimetypes
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Cookie, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from amoscloud_ai.api.routes.auth import DB_PATH, get_user_from_session

router = APIRouter(prefix="/storage", tags=["storage"])


def _storage_root() -> Path:
    """Resolve storage without requiring a privileged /data directory in local or CI runs."""
    explicit = os.getenv("AMOSCLAUD_STORAGE_PATH", "").strip()
    if explicit:
        return Path(explicit).expanduser()
    data_dir = os.getenv("DATA_DIR", "").strip()
    if data_dir:
        return Path(data_dir).expanduser() / "amosclaud-storage"
    return Path("./data/amosclaud-storage")


STORAGE_ROOT = _storage_root()
MAX_UPLOAD_BYTES = int(os.getenv("AMOSCLAUD_MAX_UPLOAD_BYTES", str(250 * 1024 * 1024)))
ADMIN_LIMIT_BYTES = int(os.getenv("AMOSCLAUD_ADMIN_STORAGE_BYTES", str(100 * 1024 * 1024 * 1024)))
DEVELOPER_INCLUDED_BYTES = int(os.getenv("AMOSCLAUD_DEVELOPER_STORAGE_BYTES", str(10 * 1024 * 1024 * 1024)))
PRO_INCLUDED_BYTES = int(os.getenv("AMOSCLAUD_PRO_STORAGE_BYTES", str(50 * 1024 * 1024 * 1024)))
ENTERPRISE_INCLUDED_BYTES = int(os.getenv("AMOSCLAUD_ENTERPRISE_STORAGE_BYTES", str(250 * 1024 * 1024 * 1024)))
ADDON_BLOCK_BYTES = int(os.getenv("AMOSCLAUD_STORAGE_ADDON_BLOCK_BYTES", str(10 * 1024 * 1024 * 1024)))
ADDON_MONTHLY_USD = float(os.getenv("AMOSCLAUD_STORAGE_ADDON_MONTHLY_USD", "2.00"))


class StorageScope:
    def __init__(self, user: sqlite3.Row, owner_type: str, owner_id: int, plan: str, quota_bytes: int):
        self.user = user
        self.owner_type = owner_type
        self.owner_id = owner_id
        self.plan = plan
        self.quota_bytes = quota_bytes

    @property
    def root(self) -> Path:
        return STORAGE_ROOT / self.owner_type / str(self.owner_id)


def _db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS storage_accounts (
            owner_type TEXT NOT NULL CHECK(owner_type IN ('admin','user','organization')),
            owner_id INTEGER NOT NULL,
            plan TEXT NOT NULL DEFAULT 'developer',
            included_bytes INTEGER NOT NULL,
            addon_blocks INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(owner_type, owner_id)
        );
        CREATE TABLE IF NOT EXISTS storage_objects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_type TEXT NOT NULL,
            owner_id INTEGER NOT NULL,
            storage_key TEXT NOT NULL,
            display_name TEXT NOT NULL,
            media_type TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            checksum_sha256 TEXT NOT NULL,
            uploaded_by INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(owner_type, owner_id, storage_key),
            FOREIGN KEY(uploaded_by) REFERENCES users(id) ON DELETE RESTRICT
        );
        """
    )
    db.commit()
    return db


def _current_user(amos_session: str | None = Cookie(default=None)) -> sqlite3.Row:
    user = get_user_from_session(amos_session)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def _scope_for_user(user: sqlite3.Row) -> StorageScope:
    owner_type = "admin" if bool(user["is_admin"]) else "user"
    owner_id = int(user["id"])
    default_plan = "admin" if owner_type == "admin" else "developer"
    default_quota = ADMIN_LIMIT_BYTES if owner_type == "admin" else DEVELOPER_INCLUDED_BYTES
    now = datetime.now(timezone.utc).isoformat()
    with _db() as db:
        db.execute(
            """INSERT OR IGNORE INTO storage_accounts
               (owner_type,owner_id,plan,included_bytes,addon_blocks,created_at,updated_at)
               VALUES (?,?,?,?,0,?,?)""",
            (owner_type, owner_id, default_plan, default_quota, now, now),
        )
        row = db.execute(
            "SELECT plan,included_bytes,addon_blocks FROM storage_accounts WHERE owner_type=? AND owner_id=?",
            (owner_type, owner_id),
        ).fetchone()
        db.commit()
    quota = int(row["included_bytes"]) + int(row["addon_blocks"]) * ADDON_BLOCK_BYTES
    return StorageScope(user, owner_type, owner_id, row["plan"], quota)


def _used_bytes(scope: StorageScope) -> int:
    with _db() as db:
        row = db.execute(
            "SELECT COALESCE(SUM(size_bytes),0) AS total FROM storage_objects WHERE owner_type=? AND owner_id=?",
            (scope.owner_type, scope.owner_id),
        ).fetchone()
    return int(row["total"])


def _safe_key(raw: str) -> str:
    value = raw.strip().replace("\\", "/").lstrip("/")
    parts = [part for part in value.split("/") if part not in {"", "."}]
    if not parts or any(part == ".." for part in parts):
        raise HTTPException(status_code=422, detail="Invalid storage key")
    return "/".join(parts)


@router.get("/me")
async def storage_overview(user: sqlite3.Row = Depends(_current_user)):
    scope = _scope_for_user(user)
    used = _used_bytes(scope)
    return {
        "owner_type": scope.owner_type,
        "owner_id": scope.owner_id,
        "plan": scope.plan,
        "used_bytes": used,
        "quota_bytes": scope.quota_bytes,
        "available_bytes": max(scope.quota_bytes - used, 0),
    }


@router.get("/me/objects")
async def list_objects(prefix: str = Query(default=""), user: sqlite3.Row = Depends(_current_user)):
    scope = _scope_for_user(user)
    with _db() as db:
        rows = db.execute(
            """SELECT id,storage_key,display_name,media_type,size_bytes,checksum_sha256,created_at,updated_at
               FROM storage_objects WHERE owner_type=? AND owner_id=? AND storage_key LIKE ? ORDER BY storage_key""",
            (scope.owner_type, scope.owner_id, f"{prefix}%"),
        ).fetchall()
    return [dict(row) for row in rows]


@router.post("/me/objects", status_code=201)
async def upload_object(
    storage_key: str,
    file: UploadFile = File(...),
    user: sqlite3.Row = Depends(_current_user),
):
    scope = _scope_for_user(user)
    key = _safe_key(storage_key)
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds maximum upload size")
    existing_size = 0
    with _db() as db:
        existing = db.execute(
            "SELECT size_bytes FROM storage_objects WHERE owner_type=? AND owner_id=? AND storage_key=?",
            (scope.owner_type, scope.owner_id, key),
        ).fetchone()
        if existing:
            existing_size = int(existing["size_bytes"])
    if _used_bytes(scope) - existing_size + len(content) > scope.quota_bytes:
        raise HTTPException(status_code=413, detail="Storage quota exceeded")
    target = scope.root / key
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    checksum = hashlib.sha256(content).hexdigest()
    now = datetime.now(timezone.utc).isoformat()
    media_type = file.content_type or mimetypes.guess_type(file.filename or key)[0] or "application/octet-stream"
    with _db() as db:
        db.execute(
            """INSERT INTO storage_objects(owner_type,owner_id,storage_key,display_name,media_type,size_bytes,
               checksum_sha256,uploaded_by,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(owner_type,owner_id,storage_key) DO UPDATE SET display_name=excluded.display_name,
               media_type=excluded.media_type,size_bytes=excluded.size_bytes,checksum_sha256=excluded.checksum_sha256,
               uploaded_by=excluded.uploaded_by,updated_at=excluded.updated_at""",
            (scope.owner_type, scope.owner_id, key, file.filename or Path(key).name, media_type, len(content), checksum,
             int(user["id"]), now, now),
        )
        db.commit()
    return {"storage_key": key, "display_name": file.filename or Path(key).name, "size_bytes": len(content), "checksum_sha256": checksum}


@router.get("/me/objects/{storage_key:path}")
async def download_object(storage_key: str, user: sqlite3.Row = Depends(_current_user)):
    scope = _scope_for_user(user)
    key = _safe_key(storage_key)
    with _db() as db:
        row = db.execute(
            "SELECT display_name,media_type FROM storage_objects WHERE owner_type=? AND owner_id=? AND storage_key=?",
            (scope.owner_type, scope.owner_id, key),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Storage object not found")
    target = scope.root / key
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Storage object data is missing")
    return FileResponse(target, media_type=row["media_type"], filename=row["display_name"])


@router.delete("/me/objects/{storage_key:path}", status_code=204)
async def delete_object(storage_key: str, user: sqlite3.Row = Depends(_current_user)) -> None:
    scope = _scope_for_user(user)
    key = _safe_key(storage_key)
    target = scope.root / key
    with _db() as db:
        result = db.execute(
            "DELETE FROM storage_objects WHERE owner_type=? AND owner_id=? AND storage_key=?",
            (scope.owner_type, scope.owner_id, key),
        )
        db.commit()
    if not result.rowcount:
        raise HTTPException(status_code=404, detail="Storage object not found")
    target.unlink(missing_ok=True)

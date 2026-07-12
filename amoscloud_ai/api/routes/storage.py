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

STORAGE_ROOT = Path(os.getenv("AMOSCLAUD_STORAGE_PATH", "/data/amosclaud-storage"))
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
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def _plan_quota(plan: str) -> int:
    return {
        "developer": DEVELOPER_INCLUDED_BYTES,
        "pro": PRO_INCLUDED_BYTES,
        "enterprise": ENTERPRISE_INCLUDED_BYTES,
    }.get(plan, DEVELOPER_INCLUDED_BYTES)


def _ensure_account(db: sqlite3.Connection, owner_type: str, owner_id: int, plan: str) -> sqlite3.Row:
    now = datetime.now(timezone.utc).isoformat()
    included = ADMIN_LIMIT_BYTES if owner_type == "admin" else _plan_quota(plan)
    db.execute(
        """INSERT OR IGNORE INTO storage_accounts(owner_type,owner_id,plan,included_bytes,addon_blocks,created_at,updated_at)
           VALUES (?,?,?,?,0,?,?)""",
        (owner_type, owner_id, plan, included, now, now),
    )
    db.commit()
    return db.execute(
        "SELECT * FROM storage_accounts WHERE owner_type=? AND owner_id=?",
        (owner_type, owner_id),
    ).fetchone()


def _scope(user: sqlite3.Row, admin: bool = False) -> StorageScope:
    owner_type = "admin" if admin else "user"
    if admin and not bool(user["is_admin"]):
        raise HTTPException(status_code=403, detail="Administrator access required")
    plan = "enterprise" if admin else "developer"
    with _db() as db:
        account = _ensure_account(db, owner_type, user["id"], plan)
    quota = int(account["included_bytes"]) + int(account["addon_blocks"]) * ADDON_BLOCK_BYTES
    return StorageScope(user, owner_type, user["id"], account["plan"], quota)


def _safe_key(value: str) -> str:
    cleaned = value.strip().replace("\\", "/").strip("/")
    path = Path(cleaned)
    if not cleaned or path.is_absolute() or ".." in path.parts or path.parts[0].startswith("."):
        raise HTTPException(status_code=422, detail="Invalid storage path")
    return "/".join(path.parts)


def _usage(scope: StorageScope) -> int:
    with _db() as db:
        row = db.execute(
            "SELECT COALESCE(SUM(size_bytes),0) AS used FROM storage_objects WHERE owner_type=? AND owner_id=?",
            (scope.owner_type, scope.owner_id),
        ).fetchone()
    return int(row["used"])


def _overview(scope: StorageScope) -> dict:
    used = _usage(scope)
    return {
        "name": "Amosclaud Storage",
        "location": "admin" if scope.owner_type == "admin" else "developer",
        "owner_type": scope.owner_type,
        "owner_id": scope.owner_id,
        "plan": scope.plan,
        "used_bytes": used,
        "quota_bytes": scope.quota_bytes,
        "available_bytes": max(scope.quota_bytes - used, 0),
        "addon": {
            "block_bytes": ADDON_BLOCK_BYTES,
            "monthly_usd": ADDON_MONTHLY_USD,
            "billing_status": "configuration_only",
        },
        "persistent_path": str(scope.root),
        "persistent_volume_required": str(STORAGE_ROOT).startswith("/data/"),
    }


@router.get("/me")
def my_storage(user: sqlite3.Row = Depends(_current_user)) -> dict:
    return _overview(_scope(user))


@router.get("/admin")
def admin_storage(user: sqlite3.Row = Depends(_current_user)) -> dict:
    return _overview(_scope(user, admin=True))


def _list(scope: StorageScope, prefix: str) -> list[dict]:
    with _db() as db:
        if prefix:
            safe_prefix = _safe_key(prefix)
            rows = db.execute(
                """SELECT * FROM storage_objects WHERE owner_type=? AND owner_id=? AND storage_key LIKE ?
                   ORDER BY storage_key""",
                (scope.owner_type, scope.owner_id, f"{safe_prefix}%"),
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT * FROM storage_objects WHERE owner_type=? AND owner_id=? ORDER BY storage_key",
                (scope.owner_type, scope.owner_id),
            ).fetchall()
    return [dict(row) for row in rows]


@router.get("/me/objects")
def my_objects(prefix: str = Query(default="", max_length=500), user: sqlite3.Row = Depends(_current_user)) -> list[dict]:
    return _list(_scope(user), prefix)


@router.get("/admin/objects")
def admin_objects(prefix: str = Query(default="", max_length=500), user: sqlite3.Row = Depends(_current_user)) -> list[dict]:
    return _list(_scope(user, admin=True), prefix)


async def _upload(scope: StorageScope, key: str, file: UploadFile) -> dict:
    storage_key = _safe_key(key)
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds the maximum upload size")

    with _db() as db:
        previous = db.execute(
            "SELECT size_bytes FROM storage_objects WHERE owner_type=? AND owner_id=? AND storage_key=?",
            (scope.owner_type, scope.owner_id, storage_key),
        ).fetchone()
    projected = _usage(scope) - (int(previous["size_bytes"]) if previous else 0) + len(content)
    if projected > scope.quota_bytes:
        raise HTTPException(status_code=413, detail="Amosclaud Storage quota exceeded")

    target = scope.root / storage_key
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".uploading")
    temporary.write_bytes(content)
    temporary.replace(target)

    checksum = hashlib.sha256(content).hexdigest()
    media_type = file.content_type or mimetypes.guess_type(file.filename or storage_key)[0] or "application/octet-stream"
    now = datetime.now(timezone.utc).isoformat()
    with _db() as db:
        db.execute(
            """INSERT INTO storage_objects(owner_type,owner_id,storage_key,display_name,media_type,size_bytes,checksum_sha256,uploaded_by,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(owner_type,owner_id,storage_key) DO UPDATE SET
                 display_name=excluded.display_name,media_type=excluded.media_type,size_bytes=excluded.size_bytes,
                 checksum_sha256=excluded.checksum_sha256,uploaded_by=excluded.uploaded_by,updated_at=excluded.updated_at""",
            (
                scope.owner_type,
                scope.owner_id,
                storage_key,
                file.filename or Path(storage_key).name,
                media_type,
                len(content),
                checksum,
                scope.user["id"],
                now,
                now,
            ),
        )
        db.commit()
    return {"storage_key": storage_key, "size_bytes": len(content), "checksum_sha256": checksum, "created_at": now}


@router.post("/me/objects", status_code=201)
async def upload_my_object(key: str, file: UploadFile = File(...), user: sqlite3.Row = Depends(_current_user)) -> dict:
    return await _upload(_scope(user), key, file)


@router.post("/admin/objects", status_code=201)
async def upload_admin_object(key: str, file: UploadFile = File(...), user: sqlite3.Row = Depends(_current_user)) -> dict:
    return await _upload(_scope(user, admin=True), key, file)


def _download(scope: StorageScope, storage_key: str) -> FileResponse:
    safe_key = _safe_key(storage_key)
    path = scope.root / safe_key
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Storage object not found")
    with _db() as db:
        row = db.execute(
            "SELECT display_name,media_type FROM storage_objects WHERE owner_type=? AND owner_id=? AND storage_key=?",
            (scope.owner_type, scope.owner_id, safe_key),
        ).fetchone()
    return FileResponse(path, media_type=row["media_type"] if row else None, filename=row["display_name"] if row else path.name)


@router.get("/me/objects/{storage_key:path}")
def download_my_object(storage_key: str, user: sqlite3.Row = Depends(_current_user)) -> FileResponse:
    return _download(_scope(user), storage_key)


@router.get("/admin/objects/{storage_key:path}")
def download_admin_object(storage_key: str, user: sqlite3.Row = Depends(_current_user)) -> FileResponse:
    return _download(_scope(user, admin=True), storage_key)


def _delete(scope: StorageScope, storage_key: str) -> None:
    safe_key = _safe_key(storage_key)
    path = scope.root / safe_key
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Storage object not found")
    path.unlink()
    with _db() as db:
        db.execute(
            "DELETE FROM storage_objects WHERE owner_type=? AND owner_id=? AND storage_key=?",
            (scope.owner_type, scope.owner_id, safe_key),
        )
        db.commit()


@router.delete("/me/objects/{storage_key:path}", status_code=204)
def delete_my_object(storage_key: str, user: sqlite3.Row = Depends(_current_user)) -> None:
    _delete(_scope(user), storage_key)


@router.delete("/admin/objects/{storage_key:path}", status_code=204)
def delete_admin_object(storage_key: str, user: sqlite3.Row = Depends(_current_user)) -> None:
    _delete(_scope(user, admin=True), storage_key)

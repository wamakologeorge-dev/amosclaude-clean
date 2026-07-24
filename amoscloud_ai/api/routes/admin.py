"""Administrator-only platform dashboard and management API."""

from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Response
from pydantic import BaseModel

from amoscloud_ai.api.routes import auth as auth_routes
from amoscloud_ai.api.routes.repositories import REPOSITORY_ROOT

router = APIRouter(prefix="/admin", tags=["administration"])


class UserUpdate(BaseModel):
    is_admin: bool | None = None
    is_suspended: bool | None = None


def _db() -> sqlite3.Connection:
    """Open the canonical auth database and apply non-destructive admin schema updates."""
    db = auth_routes._connect()
    db.execute("PRAGMA foreign_keys = ON")
    user_columns = {row[1] for row in db.execute("PRAGMA table_info(users)").fetchall()}
    if "is_suspended" not in user_columns:
        db.execute("ALTER TABLE users ADD COLUMN is_suspended INTEGER NOT NULL DEFAULT 0")
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS admin_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_user_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            target_type TEXT NOT NULL,
            target_id TEXT,
            details TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            FOREIGN KEY(admin_user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """
    )
    db.commit()
    return db


def _admin_user(amos_session: str | None = Cookie(default=None)) -> sqlite3.Row:
    user = auth_routes.get_user_from_session(amos_session)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if not bool(user["is_admin"]):
        raise HTTPException(status_code=403, detail="Administrator access required")
    return user


def _table_exists(db: sqlite3.Connection, name: str) -> bool:
    return bool(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone())


def _table_columns(db: sqlite3.Connection, name: str) -> set[str]:
    if not _table_exists(db, name):
        return set()
    return {str(row[1]) for row in db.execute(f'PRAGMA table_info("{name}")').fetchall()}


def _count(db: sqlite3.Connection, table: str) -> int:
    if not _table_exists(db, table):
        return 0
    return int(db.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])


def _directory_size(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for item in path.rglob("*"):
        try:
            if item.is_file():
                total += item.stat().st_size
        except OSError:
            continue
    return total


def _audit(db: sqlite3.Connection, admin_id: int, action: str, target_type: str, target_id: str = "", details: str = "") -> None:
    db.execute(
        "INSERT INTO admin_audit_log(admin_user_id,action,target_type,target_id,details,created_at) VALUES (?,?,?,?,?,?)",
        (admin_id, action, target_type, target_id, details, datetime.now(timezone.utc).isoformat()),
    )


def is_session_suspended(token: str | None) -> bool:
    if not token:
        return False
    import hashlib

    with _db() as db:
        row = db.execute(
            """SELECT COALESCE(u.is_suspended,0) AS is_suspended
               FROM sessions s JOIN users u ON u.id=s.user_id
               WHERE s.token_hash=?""",
            (hashlib.sha256(token.encode()).hexdigest(),),
        ).fetchone()
    return bool(row and row["is_suspended"])


@router.get("/overview")
def overview(admin: sqlite3.Row = Depends(_admin_user)) -> dict:
    del admin
    with _db() as db:
        users = _count(db, "users")
        suspended = int(db.execute("SELECT COUNT(*) FROM users WHERE is_suspended=1").fetchone()[0])
        admins = int(db.execute("SELECT COUNT(*) FROM users WHERE is_admin=1").fetchone()[0])
        active_sessions = _count(db, "sessions")
        repositories = _count(db, "repositories")
        pipelines = _count(db, "pipelines")
        deployments = _count(db, "deployments")
        mail_messages = _count(db, "mail_messages") + _count(db, "messages")
        community_posts = _count(db, "community_posts") + _count(db, "posts")
    db_path = auth_routes.DB_PATH
    return {
        "users": users,
        "administrators": admins,
        "suspended_users": suspended,
        "active_sessions": active_sessions,
        "repositories": repositories,
        "pipelines": pipelines,
        "deployments": deployments,
        "mail_messages": mail_messages,
        "community_posts": community_posts,
        "repository_storage_bytes": _directory_size(REPOSITORY_ROOT),
        "database_bytes": db_path.stat().st_size if db_path.exists() else 0,
        "status": "operational",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/users")
def list_users(
    search: str = Query(default="", max_length=120),
    limit: int = Query(default=100, ge=1, le=500),
    admin: sqlite3.Row = Depends(_admin_user),
) -> list[dict]:
    """List users even when optional repository/session tables are absent or use another schema."""
    del admin
    cleaned = search.strip()
    pattern = f"%{cleaned}%"
    with _db() as db:
        repository_columns = _table_columns(db, "repositories")
        session_columns = _table_columns(db, "sessions")
        has_repositories = {"id", "owner_id"}.issubset(repository_columns)
        has_sessions = {"token_hash", "user_id"}.issubset(session_columns)

        repository_join = "LEFT JOIN repositories r ON r.owner_id=u.id" if has_repositories else ""
        session_join = "LEFT JOIN sessions s ON s.user_id=u.id" if has_sessions else ""
        repository_count = "COUNT(DISTINCT r.id)" if has_repositories else "0"
        session_count = "COUNT(DISTINCT s.token_hash)" if has_sessions else "0"

        rows = db.execute(
            f"""SELECT u.id,u.name,u.email,u.provider,u.is_admin,u.is_suspended,u.created_at,
                       {repository_count} AS repository_count,
                       {session_count} AS session_count
                FROM users u
                {repository_join}
                {session_join}
                WHERE (?='' OR u.name LIKE ? OR u.email LIKE ?)
                GROUP BY u.id
                ORDER BY u.created_at DESC LIMIT ?""",
            (cleaned, pattern, pattern, limit),
        ).fetchall()
    return [dict(row) for row in rows]


@router.patch("/users/{user_id}")
def update_user(user_id: int, body: UserUpdate, admin: sqlite3.Row = Depends(_admin_user)) -> dict:
    if user_id == admin["id"] and (body.is_admin is False or body.is_suspended is True):
        raise HTTPException(status_code=409, detail="You cannot remove or suspend your own administrator account")
    with _db() as db:
        target = db.execute("SELECT id,name,email,is_admin,is_suspended FROM users WHERE id=?", (user_id,)).fetchone()
        if not target:
            raise HTTPException(status_code=404, detail="User not found")
        updates: list[str] = []
        values: list[int] = []
        if body.is_admin is not None:
            if target["is_admin"] and body.is_admin is False:
                admin_count = db.execute("SELECT COUNT(*) FROM users WHERE is_admin=1").fetchone()[0]
                if admin_count <= 1:
                    raise HTTPException(status_code=409, detail="Amosclaud must keep at least one administrator")
            updates.append("is_admin=?")
            values.append(int(body.is_admin))
        if body.is_suspended is not None:
            updates.append("is_suspended=?")
            values.append(int(body.is_suspended))
        if not updates:
            raise HTTPException(status_code=422, detail="No user changes supplied")
        values.append(user_id)
        db.execute(f"UPDATE users SET {', '.join(updates)} WHERE id=?", values)
        if body.is_suspended is True and _table_exists(db, "sessions"):
            db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        _audit(db, admin["id"], "update_user", "user", str(user_id), str(body.model_dump(exclude_none=True)))
        db.commit()
        row = db.execute("SELECT id,name,email,provider,is_admin,is_suspended,created_at FROM users WHERE id=?", (user_id,)).fetchone()
    return dict(row)


@router.get("/repositories")
def list_all_repositories(admin: sqlite3.Row = Depends(_admin_user)) -> list[dict]:
    del admin
    with _db() as db:
        columns = _table_columns(db, "repositories")
        if not {"id", "name", "owner_id"}.issubset(columns):
            return []
        rows = db.execute(
            """SELECT r.id,r.name,r.description,r.visibility,r.default_branch,r.created_at,r.updated_at,
                      u.id AS owner_id,u.name AS owner_name,u.email AS owner_email
               FROM repositories r JOIN users u ON u.id=r.owner_id
               ORDER BY r.updated_at DESC LIMIT 500"""
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["storage_bytes"] = _directory_size(REPOSITORY_ROOT / str(row["id"]))
        result.append(item)
    return result


@router.delete("/repositories/{repository_id}", status_code=204)
def remove_repository(repository_id: int, admin: sqlite3.Row = Depends(_admin_user)) -> Response:
    with _db() as db:
        if not {"id", "name", "owner_id"}.issubset(_table_columns(db, "repositories")):
            raise HTTPException(status_code=404, detail="Repository not found")
        row = db.execute("SELECT id,name,owner_id FROM repositories WHERE id=?", (repository_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Repository not found")
        db.execute("DELETE FROM repositories WHERE id=?", (repository_id,))
        _audit(db, admin["id"], "delete_repository", "repository", str(repository_id), row["name"])
        db.commit()
    shutil.rmtree(REPOSITORY_ROOT / str(repository_id), ignore_errors=True)
    return Response(status_code=204)


@router.get("/audit")
def audit_log(limit: int = Query(default=100, ge=1, le=500), admin: sqlite3.Row = Depends(_admin_user)) -> list[dict]:
    del admin
    with _db() as db:
        rows = db.execute(
            """SELECT a.id,a.action,a.target_type,a.target_id,a.details,a.created_at,
                      u.name AS admin_name,u.email AS admin_email
               FROM admin_audit_log a JOIN users u ON u.id=a.admin_user_id
               ORDER BY a.id DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


@router.get("/metadata")
def platform_metadata(admin: sqlite3.Row = Depends(_admin_user)) -> dict:
    """Return the redacted Amosclaud.py platform snapshot."""
    del admin
    from amoscloud_ai.Amosclaud import AmosclaudDashboard

    return AmosclaudDashboard().snapshot()


@router.post("/engineering-verification/run")
def run_engineering_verification(admin: sqlite3.Row = Depends(_admin_user)) -> dict:
    """Run bounded checks and retain a report before engineering completion is claimed."""
    from amoscloud_ai.engineering_verification import EngineeringVerification

    report = EngineeringVerification().run()
    with _db() as db:
        _audit(
            db,
            int(admin["id"]),
            "engineering_verification",
            "commit",
            str(report.get("commit_sha", "")),
            str(report.get("status", "failed")),
        )
        db.commit()
    return report


@router.get("/engineering-verification/reports")
def engineering_verification_reports(
    limit: int = Query(default=50, ge=1, le=200),
    admin: sqlite3.Row = Depends(_admin_user),
) -> list[dict]:
    del admin
    from amoscloud_ai.engineering_verification import EngineeringVerification

    return EngineeringVerification().reports(limit)


@router.get("/merge-results")
def merge_results(
    limit: int = Query(default=100, ge=1, le=500),
    admin: sqlite3.Row = Depends(_admin_user),
) -> list[dict]:
    """Show first-parent repository history joined to retained verification evidence."""
    del admin
    from amoscloud_ai.engineering_verification import EngineeringVerification

    return EngineeringVerification().merge_results(limit)

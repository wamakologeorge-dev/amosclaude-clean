"""Organization accounts and repository ownership for Amosclaud."""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Cookie, Depends, HTTPException
from pydantic import BaseModel, Field

from amoscloud_ai.api.routes.auth import DB_PATH, get_user_from_session

router = APIRouter(prefix="/organizations", tags=["organizations"])
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")


class OrganizationCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    slug: str = Field(..., min_length=2, max_length=63)


class OrganizationMemberAdd(BaseModel):
    email: str = Field(..., min_length=5, max_length=254)
    role: Literal["admin", "developer", "viewer"] = "developer"


class RepositoryAttach(BaseModel):
    repository_id: int


def _db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS organizations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            slug TEXT NOT NULL UNIQUE COLLATE NOCASE,
            owner_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(owner_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS organization_members (
            organization_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('owner','admin','developer','viewer')),
            created_at TEXT NOT NULL,
            PRIMARY KEY(organization_id, user_id),
            FOREIGN KEY(organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS organization_repositories (
            organization_id INTEGER NOT NULL,
            repository_id INTEGER NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            PRIMARY KEY(organization_id, repository_id),
            FOREIGN KEY(organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
            FOREIGN KEY(repository_id) REFERENCES repositories(id) ON DELETE CASCADE
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


def _membership(db: sqlite3.Connection, organization_id: int, user_id: int) -> sqlite3.Row:
    row = db.execute(
        """SELECT o.*, m.role FROM organizations o
           JOIN organization_members m ON m.organization_id=o.id
           WHERE o.id=? AND m.user_id=?""",
        (organization_id, user_id),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Organization not found")
    return row


def _require_admin(row: sqlite3.Row) -> None:
    if row["role"] not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="Organization administrator access required")


@router.post("", status_code=201)
def create_organization(body: OrganizationCreate, user: sqlite3.Row = Depends(_current_user)) -> dict:
    slug = body.slug.strip().lower()
    if not _SLUG_RE.fullmatch(slug):
        raise HTTPException(status_code=422, detail="Use lowercase letters, numbers, and hyphens for the organization path")
    now = datetime.now(timezone.utc).isoformat()
    with _db() as db:
        try:
            cursor = db.execute(
                "INSERT INTO organizations(name,slug,owner_id,created_at) VALUES (?,?,?,?)",
                (body.name.strip(), slug, user["id"], now),
            )
            organization_id = cursor.lastrowid
            db.execute(
                "INSERT INTO organization_members(organization_id,user_id,role,created_at) VALUES (?,?, 'owner', ?)",
                (organization_id, user["id"], now),
            )
            db.commit()
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="Organization path is already taken") from exc
    return {"id": organization_id, "name": body.name.strip(), "slug": slug, "role": "owner", "path": f"/organizations/{slug}"}


@router.get("")
def list_organizations(user: sqlite3.Row = Depends(_current_user)) -> list[dict]:
    with _db() as db:
        rows = db.execute(
            """SELECT o.id,o.name,o.slug,m.role,o.created_at
               FROM organizations o JOIN organization_members m ON m.organization_id=o.id
               WHERE m.user_id=? ORDER BY o.name""",
            (user["id"],),
        ).fetchall()
    return [{**dict(row), "path": f"/organizations/{row['slug']}"} for row in rows]


@router.post("/{organization_id}/members", status_code=201)
def add_member(organization_id: int, body: OrganizationMemberAdd, user: sqlite3.Row = Depends(_current_user)) -> dict:
    with _db() as db:
        membership = _membership(db, organization_id, user["id"])
        _require_admin(membership)
        member = db.execute("SELECT id,name,email FROM users WHERE email=?", (body.email.strip().lower(),)).fetchone()
        if not member:
            raise HTTPException(status_code=404, detail="User not found")
        db.execute(
            """INSERT INTO organization_members(organization_id,user_id,role,created_at)
               VALUES (?,?,?,?) ON CONFLICT(organization_id,user_id) DO UPDATE SET role=excluded.role""",
            (organization_id, member["id"], body.role, datetime.now(timezone.utc).isoformat()),
        )
        db.commit()
    return {"user_id": member["id"], "name": member["name"], "email": member["email"], "role": body.role}


@router.post("/{organization_id}/repositories", status_code=201)
def attach_repository(organization_id: int, body: RepositoryAttach, user: sqlite3.Row = Depends(_current_user)) -> dict:
    with _db() as db:
        membership = _membership(db, organization_id, user["id"])
        _require_admin(membership)
        repository = db.execute("SELECT id,name,owner_id FROM repositories WHERE id=?", (body.repository_id,)).fetchone()
        if not repository:
            raise HTTPException(status_code=404, detail="Repository not found")
        if repository["owner_id"] != user["id"] and membership["role"] != "owner":
            raise HTTPException(status_code=403, detail="Only the repository owner can move it into an organization")
        try:
            db.execute(
                "INSERT INTO organization_repositories(organization_id,repository_id,created_at) VALUES (?,?,?)",
                (organization_id, body.repository_id, datetime.now(timezone.utc).isoformat()),
            )
            db.commit()
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="Repository already belongs to an organization") from exc
    return {
        "organization_id": organization_id,
        "repository_id": body.repository_id,
        "path": f"/organizations/{membership['slug']}/repositories/{repository['name']}",
    }

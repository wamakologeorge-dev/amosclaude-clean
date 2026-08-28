"""Amosclaud-native developer applications and organization installations."""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from amoscloud_ai.api.routes import organizations

router = APIRouter(tags=["applications", "integrations"])

SCOPES = {
    "repository:read": "Read repositories available to the installation.",
    "repository:write": "Create and modify repository content within approved workspaces.",
    "workspace:read": "Inspect files, tasks, and workspace metadata.",
    "workspace:execute": "Run commands in an approved Amosclaud workspace.",
    "agent:invoke": "Invoke Amosclaud Agent for approved organization work.",
    "spacecodeme:use": "Open and operate Amosclaud SpaceCodeMe workspaces.",
    "actions:execute": "Run Amosclaud Actions approved for the organization.",
    "deployment:staging": "Deploy to approved non-production environments.",
    "deployment:production": "Request or perform production deployment when policy also permits it.",
    "storage:read": "Read approved application storage.",
    "storage:write": "Write approved application storage.",
    "webhooks:manage": "Create and manage application webhooks.",
}


class ApplicationCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    description: str = Field(default="", max_length=500)
    visibility: Literal["private", "selected", "public"] = "private"
    requested_scopes: list[str] = Field(default_factory=list, max_length=30)
    homepage_url: str | None = Field(default=None, max_length=500)


class ApplicationInstall(BaseModel):
    scopes: list[str] = Field(default_factory=list, max_length=30)


class CredentialCreate(BaseModel):
    expires_in_days: int = Field(default=90, ge=1, le=365)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: list[str]) -> str:
    return json.dumps(sorted(set(value)), separators=(",", ":"))


def _scopes(raw: str | None) -> list[str]:
    try:
        value = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    return [item for item in value if isinstance(item, str)]


def _validate_scopes(values: list[str]) -> list[str]:
    unknown = sorted(set(values) - SCOPES.keys())
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown application scopes: {', '.join(unknown)}")
    return sorted(set(values))


def _ensure_tables(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS developer_applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            client_id TEXT NOT NULL UNIQUE,
            description TEXT NOT NULL DEFAULT '',
            visibility TEXT NOT NULL DEFAULT 'private',
            requested_scopes TEXT NOT NULL DEFAULT '[]',
            homepage_url TEXT,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(owner_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS application_installations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            application_id INTEGER NOT NULL,
            organization_id INTEGER NOT NULL,
            installed_by INTEGER NOT NULL,
            scopes TEXT NOT NULL DEFAULT '[]',
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            revoked_at TEXT,
            UNIQUE(application_id, organization_id),
            FOREIGN KEY(application_id) REFERENCES developer_applications(id) ON DELETE CASCADE,
            FOREIGN KEY(organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
            FOREIGN KEY(installed_by) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS application_credentials (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            installation_id INTEGER NOT NULL,
            token_prefix TEXT NOT NULL,
            token_hash TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            revoked_at TEXT,
            FOREIGN KEY(installation_id) REFERENCES application_installations(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS application_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            application_id INTEGER NOT NULL,
            installation_id INTEGER,
            organization_id INTEGER,
            actor_user_id INTEGER,
            action TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(application_id) REFERENCES developer_applications(id) ON DELETE CASCADE
        );
        """
    )


def _db() -> sqlite3.Connection:
    db = organizations._db()
    _ensure_tables(db)
    db.commit()
    return db


def _audit(
    db: sqlite3.Connection,
    *,
    application_id: int,
    action: str,
    actor_user_id: int,
    installation_id: int | None = None,
    organization_id: int | None = None,
) -> None:
    db.execute(
        """INSERT INTO application_audit_log(
               application_id,installation_id,organization_id,actor_user_id,action,created_at
           ) VALUES (?,?,?,?,?,?)""",
        (application_id, installation_id, organization_id, actor_user_id, action, _now()),
    )


def _application_dict(row: sqlite3.Row) -> dict:
    result = dict(row)
    result["requested_scopes"] = _scopes(result.get("requested_scopes"))
    return result


def _installation_dict(row: sqlite3.Row) -> dict:
    result = dict(row)
    result["scopes"] = _scopes(result.get("scopes"))
    return result


@router.get("/applications/scopes")
def list_application_scopes(
    user: sqlite3.Row = Depends(organizations._current_user),
) -> dict:
    return {"scopes": [{"name": name, "description": description} for name, description in SCOPES.items()]}


@router.post("/applications", status_code=201)
def create_application(
    body: ApplicationCreate,
    user: sqlite3.Row = Depends(organizations._current_user),
) -> dict:
    requested = _validate_scopes(body.requested_scopes)
    now = _now()
    client_id = f"amosapp_{secrets.token_urlsafe(18).replace('-', '').replace('_', '')}"
    with _db() as db:
        cursor = db.execute(
            """INSERT INTO developer_applications(
                   owner_id,name,client_id,description,visibility,requested_scopes,
                   homepage_url,status,created_at,updated_at
               ) VALUES (?,?,?,?,?,?,?,'active',?,?)""",
            (
                user["id"], body.name.strip(), client_id, body.description.strip(),
                body.visibility, _json(requested), body.homepage_url, now, now,
            ),
        )
        application_id = int(cursor.lastrowid)
        _audit(db, application_id=application_id, action="application.created", actor_user_id=user["id"])
        db.commit()
        row = db.execute("SELECT * FROM developer_applications WHERE id=?", (application_id,)).fetchone()
    return _application_dict(row)


@router.get("/applications")
def list_developer_applications(
    user: sqlite3.Row = Depends(organizations._current_user),
) -> list[dict]:
    with _db() as db:
        rows = db.execute(
            "SELECT * FROM developer_applications WHERE owner_id=? AND status='active' ORDER BY created_at DESC",
            (user["id"],),
        ).fetchall()
    return [_application_dict(row) for row in rows]


@router.get("/applications/{application_id}")
def get_application(
    application_id: int,
    user: sqlite3.Row = Depends(organizations._current_user),
) -> dict:
    with _db() as db:
        row = db.execute("SELECT * FROM developer_applications WHERE id=? AND status='active'", (application_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Application not found")
        if row["owner_id"] != user["id"] and row["visibility"] != "public":
            raise HTTPException(status_code=404, detail="Application not found")
    return _application_dict(row)


@router.post("/organizations/{organization_id}/applications/{application_id}/install", status_code=201)
def install_application(
    organization_id: int,
    application_id: int,
    body: ApplicationInstall,
    user: sqlite3.Row = Depends(organizations._current_user),
) -> dict:
    approved = _validate_scopes(body.scopes)
    now = _now()
    with _db() as db:
        membership = organizations._membership(db, organization_id, user["id"])
        organizations._require_admin(membership)
        application = db.execute("SELECT * FROM developer_applications WHERE id=? AND status='active'", (application_id,)).fetchone()
        if not application:
            raise HTTPException(status_code=404, detail="Application not found")
        requested = set(_scopes(application["requested_scopes"]))
        if not set(approved).issubset(requested):
            raise HTTPException(status_code=422, detail="An installation can only grant scopes requested by the application")
        if application["visibility"] == "private" and application["owner_id"] != user["id"]:
            raise HTTPException(status_code=403, detail="This application is private")
        existing = db.execute(
            "SELECT id,status FROM application_installations WHERE application_id=? AND organization_id=?",
            (application_id, organization_id),
        ).fetchone()
        if existing and existing["status"] == "active":
            raise HTTPException(status_code=409, detail="Application is already installed")
        if existing:
            installation_id = existing["id"]
            db.execute(
                """UPDATE application_installations SET installed_by=?,scopes=?,status='active',
                   updated_at=?,revoked_at=NULL WHERE id=?""",
                (user["id"], _json(approved), now, installation_id),
            )
        else:
            cursor = db.execute(
                """INSERT INTO application_installations(
                       application_id,organization_id,installed_by,scopes,status,created_at,updated_at
                   ) VALUES (?,?,?,?,'active',?,?)""",
                (application_id, organization_id, user["id"], _json(approved), now, now),
            )
            installation_id = int(cursor.lastrowid)
        _audit(
            db, application_id=application_id, installation_id=installation_id,
            organization_id=organization_id, action="installation.installed", actor_user_id=user["id"],
        )
        db.commit()
        row = db.execute(
            """SELECT i.*,a.name AS application_name,a.client_id FROM application_installations i
               JOIN developer_applications a ON a.id=i.application_id WHERE i.id=?""",
            (installation_id,),
        ).fetchone()
    return _installation_dict(row)


@router.get("/organizations/{organization_id}/applications")
def list_installed_applications(
    organization_id: int,
    user: sqlite3.Row = Depends(organizations._current_user),
) -> list[dict]:
    with _db() as db:
        organizations._membership(db, organization_id, user["id"])
        rows = db.execute(
            """SELECT i.*,a.name AS application_name,a.client_id,a.description
               FROM application_installations i JOIN developer_applications a ON a.id=i.application_id
               WHERE i.organization_id=? AND i.status='active' ORDER BY i.created_at DESC""",
            (organization_id,),
        ).fetchall()
    return [_installation_dict(row) for row in rows]


@router.post("/organizations/{organization_id}/application-installations/{installation_id}/credentials", status_code=201)
def create_installation_credential(
    organization_id: int,
    installation_id: int,
    body: CredentialCreate,
    user: sqlite3.Row = Depends(organizations._current_user),
) -> dict:
    now_dt = datetime.now(timezone.utc)
    expires = now_dt + timedelta(days=body.expires_in_days)
    raw_token = f"amos_install_{secrets.token_urlsafe(32)}"
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    token_prefix = raw_token[:18]
    with _db() as db:
        membership = organizations._membership(db, organization_id, user["id"])
        organizations._require_admin(membership)
        installation = db.execute(
            """SELECT * FROM application_installations
               WHERE id=? AND organization_id=? AND status='active'""",
            (installation_id, organization_id),
        ).fetchone()
        if not installation:
            raise HTTPException(status_code=404, detail="Application installation not found")
        cursor = db.execute(
            """INSERT INTO application_credentials(
                   installation_id,token_prefix,token_hash,status,created_at,expires_at
               ) VALUES (?,?,?,'active',?,?)""",
            (installation_id, token_prefix, token_hash, now_dt.isoformat(), expires.isoformat()),
        )
        credential_id = int(cursor.lastrowid)
        _audit(
            db, application_id=installation["application_id"], installation_id=installation_id,
            organization_id=organization_id, action="credential.created", actor_user_id=user["id"],
        )
        db.commit()
    return {
        "id": credential_id,
        "installation_id": installation_id,
        "token": raw_token,
        "token_prefix": token_prefix,
        "expires_at": expires.isoformat(),
        "warning": "Copy this token now. Amosclaud stores only its SHA-256 hash and cannot show it again.",
    }


@router.delete("/organizations/{organization_id}/application-installations/{installation_id}")
def revoke_installation(
    organization_id: int,
    installation_id: int,
    user: sqlite3.Row = Depends(organizations._current_user),
) -> dict:
    now = _now()
    with _db() as db:
        membership = organizations._membership(db, organization_id, user["id"])
        organizations._require_admin(membership)
        installation = db.execute(
            "SELECT * FROM application_installations WHERE id=? AND organization_id=? AND status='active'",
            (installation_id, organization_id),
        ).fetchone()
        if not installation:
            raise HTTPException(status_code=404, detail="Application installation not found")
        db.execute(
            "UPDATE application_installations SET status='revoked',updated_at=?,revoked_at=? WHERE id=?",
            (now, now, installation_id),
        )
        db.execute(
            "UPDATE application_credentials SET status='revoked',revoked_at=? WHERE installation_id=? AND status='active'",
            (now, installation_id),
        )
        _audit(
            db, application_id=installation["application_id"], installation_id=installation_id,
            organization_id=organization_id, action="installation.revoked", actor_user_id=user["id"],
        )
        db.commit()
    return {"installation_id": installation_id, "status": "revoked"}


def authenticate_application_token(raw_token: str) -> dict | None:
    """Resolve an active installation token without ever storing the raw credential."""
    if not raw_token.startswith("amos_install_"):
        return None
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    now = _now()
    with _db() as db:
        row = db.execute(
            """SELECT c.id AS credential_id,i.id AS installation_id,i.organization_id,
                      i.application_id,i.scopes,a.client_id,a.name AS application_name
               FROM application_credentials c
               JOIN application_installations i ON i.id=c.installation_id
               JOIN developer_applications a ON a.id=i.application_id
               WHERE c.token_hash=? AND c.status='active' AND i.status='active'
                 AND a.status='active' AND c.expires_at>?""",
            (token_hash, now),
        ).fetchone()
    return _installation_dict(row) if row else None

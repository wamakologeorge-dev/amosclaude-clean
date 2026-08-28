"""First-party Amosclaud developer applications and organization installations."""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Cookie, Depends, HTTPException
from pydantic import BaseModel, Field

from amoscloud_ai.api.routes.auth import DB_PATH, get_user_from_session

def _membership(*args, **kwargs):
    """Proxy to organizations._membership, imported lazily to avoid a circular import.

    routes/__init__ imports this module before organizations, while
    organizations imports this module at its tail to merge application routes.
    A module-level import here would therefore hand organizations a partially
    initialized module. Deferring to call time makes every import order safe.
    """
    from amoscloud_ai.api.routes.organizations import _membership as _impl

    return _impl(*args, **kwargs)


def _require_admin(*args, **kwargs):
    """Proxy to organizations._require_admin (lazy for the same reason as above)."""
    from amoscloud_ai.api.routes.organizations import _require_admin as _impl

    return _impl(*args, **kwargs)


router = APIRouter(tags=["applications", "integrations"])

SCOPE_CATALOG: dict[str, str] = {
    "repositories:read": "Read organization repositories and source metadata",
    "repositories:write": "Create or update repository content through guarded Amosclaud tools",
    "terminal:execute": "Run bounded commands in an authorized workspace terminal",
    "agent:invoke": "Invoke Amosclaud Agent for approved engineering tasks",
    "spacecodeme:use": "Open and operate an Amosclaud SpaceCodeMe development workspace",
    "actions:run": "Run approved Amosclaud Actions",
    "deployments:staging": "Deploy to authorized staging environments",
    "deployments:production": "Deploy to authorized production environments",
    "storage:read": "Read authorized Amosclaud storage resources",
    "storage:write": "Write authorized Amosclaud storage resources",
    "models:invoke": "Invoke models exposed by the Amosclaud model gateway",
    "audit:read": "Read application audit evidence for the installation",
}


class ApplicationCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    description: str = Field(default="", max_length=1000)
    visibility: Literal["private", "shared", "public"] = "private"
    requested_scopes: list[str] = Field(default_factory=list, max_length=32)
    homepage_url: str | None = Field(default=None, max_length=500)
    callback_url: str | None = Field(default=None, max_length=500)


class InstallationCreate(BaseModel):
    organization_id: int
    granted_scopes: list[str] = Field(default_factory=list, max_length=32)


class TokenCreate(BaseModel):
    name: str = Field(default="default", min_length=2, max_length=80)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_scopes(scopes: list[str]) -> list[str]:
    normalized = sorted({scope.strip().lower() for scope in scopes if scope.strip()})
    unknown = [scope for scope in normalized if scope not in SCOPE_CATALOG]
    if unknown:
        raise HTTPException(status_code=422, detail={"unknown_scopes": unknown})
    return normalized


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _current_user(amos_session: str | None = Cookie(default=None)) -> sqlite3.Row:
    user = get_user_from_session(amos_session)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def _db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS developer_applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_organization_id INTEGER NOT NULL,
            created_by INTEGER NOT NULL,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            visibility TEXT NOT NULL CHECK(visibility IN ('private','shared','public')),
            requested_scopes TEXT NOT NULL,
            homepage_url TEXT,
            callback_url TEXT,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(owner_organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
            FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS application_installations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            application_id INTEGER NOT NULL,
            organization_id INTEGER NOT NULL,
            granted_scopes TEXT NOT NULL,
            installed_by INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(application_id, organization_id),
            FOREIGN KEY(application_id) REFERENCES developer_applications(id) ON DELETE CASCADE,
            FOREIGN KEY(organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
            FOREIGN KEY(installed_by) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS application_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            installation_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            token_prefix TEXT NOT NULL,
            token_hash TEXT NOT NULL UNIQUE,
            created_by INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL,
            revoked_at TEXT,
            FOREIGN KEY(installation_id) REFERENCES application_installations(id) ON DELETE CASCADE,
            FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS application_audit_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            organization_id INTEGER NOT NULL,
            application_id INTEGER,
            installation_id INTEGER,
            actor_user_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            metadata TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            FOREIGN KEY(organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
            FOREIGN KEY(actor_user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_application_installations_org
            ON application_installations(organization_id, status);
        CREATE INDEX IF NOT EXISTS idx_application_audit_org
            ON application_audit_events(organization_id, created_at);
        """
    )
    db.commit()
    return db


def _audit(
    db: sqlite3.Connection,
    *,
    organization_id: int,
    actor_user_id: int,
    action: str,
    application_id: int | None = None,
    installation_id: int | None = None,
    metadata: dict | None = None,
) -> None:
    db.execute(
        """INSERT INTO application_audit_events(
               organization_id,application_id,installation_id,actor_user_id,
               action,metadata,created_at
           ) VALUES (?,?,?,?,?,?,?)""",
        (
            organization_id,
            application_id,
            installation_id,
            actor_user_id,
            action,
            json.dumps(metadata or {}, sort_keys=True),
            _now(),
        ),
    )


def _installation_for_admin(
    db: sqlite3.Connection, installation_id: int, user_id: int
) -> sqlite3.Row:
    row = db.execute(
        """SELECT i.*, a.name AS application_name
           FROM application_installations i
           JOIN developer_applications a ON a.id=i.application_id
           WHERE i.id=? AND i.status='active'""",
        (installation_id,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Application installation not found")
    membership = _membership(db, int(row["organization_id"]), user_id)
    _require_admin(membership)
    return row


@router.get("/integrations/scopes")
def list_application_scopes(user: sqlite3.Row = Depends(_current_user)) -> list[dict]:
    del user
    return [{"scope": scope, "description": description} for scope, description in SCOPE_CATALOG.items()]


@router.post("/organizations/{organization_id}/applications", status_code=201)
def create_application(
    organization_id: int,
    body: ApplicationCreate,
    user: sqlite3.Row = Depends(_current_user),
) -> dict:
    scopes = _normalize_scopes(body.requested_scopes)
    now = _now()
    with _db() as db:
        membership = _membership(db, organization_id, int(user["id"]))
        _require_admin(membership)
        cursor = db.execute(
            """INSERT INTO developer_applications(
                   owner_organization_id,created_by,name,description,visibility,
                   requested_scopes,homepage_url,callback_url,created_at,updated_at
               ) VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                organization_id,
                user["id"],
                body.name.strip(),
                body.description.strip(),
                body.visibility,
                json.dumps(scopes),
                body.homepage_url,
                body.callback_url,
                now,
                now,
            ),
        )
        application_id = int(cursor.lastrowid)
        _audit(
            db,
            organization_id=organization_id,
            actor_user_id=int(user["id"]),
            action="application.created",
            application_id=application_id,
            metadata={"visibility": body.visibility, "requested_scopes": scopes},
        )
        db.commit()
    return {
        "id": application_id,
        "owner_organization_id": organization_id,
        "name": body.name.strip(),
        "visibility": body.visibility,
        "requested_scopes": scopes,
    }


@router.get("/organizations/{organization_id}/applications")
def list_developer_applications(
    organization_id: int, user: sqlite3.Row = Depends(_current_user)
) -> list[dict]:
    with _db() as db:
        _membership(db, organization_id, int(user["id"]))
        rows = db.execute(
            """SELECT id,name,description,visibility,requested_scopes,
                      homepage_url,callback_url,status,created_at,updated_at
               FROM developer_applications
               WHERE owner_organization_id=? AND status='active'
               ORDER BY name""",
            (organization_id,),
        ).fetchall()
    return [
        {**dict(row), "requested_scopes": json.loads(row["requested_scopes"])}
        for row in rows
    ]


@router.post("/applications/{application_id}/installations", status_code=201)
def install_application(
    application_id: int,
    body: InstallationCreate,
    user: sqlite3.Row = Depends(_current_user),
) -> dict:
    granted = _normalize_scopes(body.granted_scopes)
    now = _now()
    with _db() as db:
        membership = _membership(db, body.organization_id, int(user["id"]))
        _require_admin(membership)
        application = db.execute(
            """SELECT * FROM developer_applications
               WHERE id=? AND status='active'""",
            (application_id,),
        ).fetchone()
        if not application:
            raise HTTPException(status_code=404, detail="Developer application not found")
        if application["visibility"] == "private" and int(application["owner_organization_id"]) != body.organization_id:
            raise HTTPException(status_code=403, detail="Private application cannot be installed in this organization")
        requested = set(json.loads(application["requested_scopes"]))
        unauthorized = sorted(set(granted) - requested)
        if unauthorized:
            raise HTTPException(
                status_code=422,
                detail={"scopes_not_requested_by_application": unauthorized},
            )
        try:
            cursor = db.execute(
                """INSERT INTO application_installations(
                       application_id,organization_id,granted_scopes,installed_by,
                       created_at,updated_at
                   ) VALUES (?,?,?,?,?,?)""",
                (application_id, body.organization_id, json.dumps(granted), user["id"], now, now),
            )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="Application is already installed") from exc
        installation_id = int(cursor.lastrowid)
        _audit(
            db,
            organization_id=body.organization_id,
            actor_user_id=int(user["id"]),
            action="application.installed",
            application_id=application_id,
            installation_id=installation_id,
            metadata={"granted_scopes": granted},
        )
        db.commit()
    return {
        "id": installation_id,
        "application_id": application_id,
        "organization_id": body.organization_id,
        "granted_scopes": granted,
        "status": "active",
    }


@router.get("/organizations/{organization_id}/application-installations")
def list_application_installations(
    organization_id: int, user: sqlite3.Row = Depends(_current_user)
) -> list[dict]:
    with _db() as db:
        _membership(db, organization_id, int(user["id"]))
        rows = db.execute(
            """SELECT i.id,i.application_id,i.organization_id,i.granted_scopes,
                      i.status,i.created_at,i.updated_at,a.name,a.description,a.visibility
               FROM application_installations i
               JOIN developer_applications a ON a.id=i.application_id
               WHERE i.organization_id=? AND i.status='active'
               ORDER BY a.name""",
            (organization_id,),
        ).fetchall()
    return [{**dict(row), "granted_scopes": json.loads(row["granted_scopes"])} for row in rows]


@router.post("/installations/{installation_id}/tokens", status_code=201)
def create_installation_token(
    installation_id: int,
    body: TokenCreate,
    user: sqlite3.Row = Depends(_current_user),
) -> dict:
    raw_token = "amos_app_" + secrets.token_urlsafe(32)
    prefix = raw_token[:18]
    with _db() as db:
        installation = _installation_for_admin(db, installation_id, int(user["id"]))
        cursor = db.execute(
            """INSERT INTO application_tokens(
                   installation_id,name,token_prefix,token_hash,created_by,created_at
               ) VALUES (?,?,?,?,?,?)""",
            (installation_id, body.name.strip(), prefix, _hash_token(raw_token), user["id"], _now()),
        )
        token_id = int(cursor.lastrowid)
        _audit(
            db,
            organization_id=int(installation["organization_id"]),
            actor_user_id=int(user["id"]),
            action="application.token_created",
            application_id=int(installation["application_id"]),
            installation_id=installation_id,
            metadata={"token_id": token_id, "prefix": prefix},
        )
        db.commit()
    return {
        "id": token_id,
        "installation_id": installation_id,
        "name": body.name.strip(),
        "token": raw_token,
        "token_prefix": prefix,
        "warning": "Store this token now. Amosclaud will not display the raw value again.",
    }


@router.get("/installations/{installation_id}/tokens")
def list_installation_tokens(
    installation_id: int, user: sqlite3.Row = Depends(_current_user)
) -> list[dict]:
    with _db() as db:
        _installation_for_admin(db, installation_id, int(user["id"]))
        rows = db.execute(
            """SELECT id,name,token_prefix,status,created_at,revoked_at
               FROM application_tokens WHERE installation_id=? ORDER BY id DESC""",
            (installation_id,),
        ).fetchall()
    return [dict(row) for row in rows]


@router.delete("/installations/{installation_id}/tokens/{token_id}", status_code=204)
def revoke_installation_token(
    installation_id: int,
    token_id: int,
    user: sqlite3.Row = Depends(_current_user),
) -> None:
    with _db() as db:
        installation = _installation_for_admin(db, installation_id, int(user["id"]))
        token = db.execute(
            "SELECT id,status FROM application_tokens WHERE id=? AND installation_id=?",
            (token_id, installation_id),
        ).fetchone()
        if not token:
            raise HTTPException(status_code=404, detail="Application token not found")
        db.execute(
            "UPDATE application_tokens SET status='revoked', revoked_at=? WHERE id=?",
            (_now(), token_id),
        )
        _audit(
            db,
            organization_id=int(installation["organization_id"]),
            actor_user_id=int(user["id"]),
            action="application.token_revoked",
            application_id=int(installation["application_id"]),
            installation_id=installation_id,
            metadata={"token_id": token_id},
        )
        db.commit()


@router.get("/organizations/{organization_id}/application-audit")
def application_audit(
    organization_id: int,
    user: sqlite3.Row = Depends(_current_user),
    limit: int = 100,
) -> list[dict]:
    limit = max(1, min(limit, 250))
    with _db() as db:
        membership = _membership(db, organization_id, int(user["id"]))
        _require_admin(membership)
        rows = db.execute(
            """SELECT id,application_id,installation_id,actor_user_id,action,metadata,created_at
               FROM application_audit_events
               WHERE organization_id=? ORDER BY id DESC LIMIT ?""",
            (organization_id, limit),
        ).fetchall()
    return [{**dict(row), "metadata": json.loads(row["metadata"])} for row in rows]

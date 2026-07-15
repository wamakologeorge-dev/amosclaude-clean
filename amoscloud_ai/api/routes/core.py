from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from amoscloud_ai.api.routes import auth as auth_routes, local_workspace
from amoscloud_ai.api.routes.admin import _admin_user
from amoscloud_ai.core.access import AccessPolicy
from amoscloud_ai.core.registry import ServiceRegistry
from amoscloud_ai.core.vault import AmosclaudVault, VaultError

router = APIRouter(prefix="/core", tags=["amosclaud-core"])


class SettingWrite(BaseModel):
    value: str = Field(max_length=32768)
    secret: bool = True


class ServiceWrite(BaseModel):
    kind: str = Field(min_length=1, max_length=80)
    endpoint: str = Field(min_length=1, max_length=2048)
    metadata: str = Field(default="{}", max_length=16384)


class OwnerClaim(BaseModel):
    confirmation: str = Field(min_length=10, max_length=80)


def _core_db_path() -> Path:
    return Path(os.getenv("AMOSCLAUD_CORE_DB", "/data/amosclaud-core.db"))


def _vault() -> AmosclaudVault:
    try:
        return AmosclaudVault(db_path=_core_db_path())
    except VaultError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _registry() -> ServiceRegistry:
    return ServiceRegistry(_core_db_path())


def _owner_db():
    db = auth_routes._connect()
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS platform_owner (
            singleton INTEGER PRIMARY KEY CHECK(singleton=1),
            user_id INTEGER NOT NULL UNIQUE,
            claimed_at TEXT NOT NULL,
            recognition_source TEXT NOT NULL DEFAULT 'owner-page',
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE RESTRICT
        )
        """
    )
    db.commit()
    return db


def _configured_owner_emails() -> set[str]:
    values = [os.getenv("AMOSCLAUD_ADMIN_EMAIL", ""), os.getenv("AMOSCLAUD_OWNER_EMAIL", "")]
    values.extend(os.getenv("AMOSCLAUD_OWNER_ALIASES", "").split(","))
    return {value.strip().lower() for value in values if value.strip()}


def owner_identity(user) -> dict:
    """Return the unified owner decision used by Runtime and Autonomous."""
    email = str(user["email"]).strip().lower()
    env_match = email in _configured_owner_emails()
    with _owner_db() as db:
        row = db.execute("SELECT user_id,claimed_at,recognition_source FROM platform_owner WHERE singleton=1").fetchone()
    db_match = bool(row and int(row["user_id"]) == int(user["id"]))
    return {
        "recognized": bool(env_match or db_match),
        "user_id": int(user["id"]),
        "name": str(user["name"]),
        "email": email,
        "is_admin": bool(user["is_admin"]),
        "source": "persistent-owner-record" if db_match else "environment-owner" if env_match else "not-recognized",
        "claimed_at": row["claimed_at"] if db_match and row else None,
    }


def _owner_user(admin=Depends(_admin_user)):
    identity = owner_identity(admin)
    if not identity["recognized"]:
        raise HTTPException(status_code=403, detail="Amosclaud owner access required. Open /owner to verify or claim the owner identity.")
    return admin


@router.get("/owner/status")
def owner_status(admin=Depends(_admin_user)) -> dict:
    identity = owner_identity(admin)
    with _owner_db() as db:
        existing = db.execute(
            "SELECT p.user_id,u.name,u.email,p.claimed_at,p.recognition_source FROM platform_owner p JOIN users u ON u.id=p.user_id WHERE p.singleton=1"
        ).fetchone()
    return {
        **identity,
        "claim_available": existing is None,
        "persistent_owner": ({"user_id": int(existing["user_id"]), "name": existing["name"], "email": existing["email"], "claimed_at": existing["claimed_at"], "source": existing["recognition_source"]} if existing else None),
        "autonomous_recognition": "owner" if identity["recognized"] else "administrator-only",
    }


@router.post("/owner/claim")
def claim_owner(body: OwnerClaim, admin=Depends(_admin_user)) -> dict:
    if body.confirmation.strip().upper() != "MAKE ME AMOSCLAUD OWNER":
        raise HTTPException(status_code=400, detail="Enter the exact confirmation: MAKE ME AMOSCLAUD OWNER")
    with _owner_db() as db:
        existing = db.execute("SELECT user_id FROM platform_owner WHERE singleton=1").fetchone()
        if existing and int(existing["user_id"]) != int(admin["id"]):
            raise HTTPException(status_code=409, detail="A different platform owner is already registered. Owner transfer requires a controlled database migration.")
        now = datetime.now(timezone.utc).isoformat()
        db.execute(
            "INSERT INTO platform_owner(singleton,user_id,claimed_at,recognition_source) VALUES(1,?,?,?) ON CONFLICT(singleton) DO UPDATE SET user_id=excluded.user_id,claimed_at=excluded.claimed_at,recognition_source=excluded.recognition_source",
            (int(admin["id"]), now, "owner-page"),
        )
        db.commit()
    return {"recognized": True, "role": "owner", "user_id": int(admin["id"]), "email": str(admin["email"]), "message": "Autonomous and Runtime now recognize this signed-in administrator as the platform owner."}


@router.get("/access")
def access_summary() -> dict:
    return AccessPolicy.from_environment().public_summary()


@router.get("/settings")
def list_settings(owner=Depends(_owner_user)) -> list[dict]:
    del owner
    return _vault().list_masked()


@router.put("/settings/{name}")
def set_setting(name: str, body: SettingWrite, owner=Depends(_owner_user)) -> dict:
    vault = _vault()
    vault.set(name, body.value, secret=body.secret, actor_id=int(owner["id"]))
    return {"name": name.strip().upper(), "saved": True, "is_secret": body.secret}


@router.delete("/settings/{name}")
def delete_setting(name: str, owner=Depends(_owner_user)) -> dict:
    deleted = _vault().delete(name, actor_id=int(owner["id"]))
    if not deleted:
        raise HTTPException(status_code=404, detail="Setting not found")
    return {"name": name.strip().upper(), "deleted": True}


@router.get("/services")
def list_services(owner=Depends(_owner_user)) -> list[dict]:
    del owner
    return _registry().list()


@router.put("/services/{name}")
def register_service(name: str, body: ServiceWrite, owner=Depends(_owner_user)) -> dict:
    del owner
    _registry().register(name, body.kind, body.endpoint, body.metadata)
    return {"name": name, "registered": True, "endpoint": body.endpoint}


@router.delete("/services/{name}")
def remove_service(name: str, owner=Depends(_owner_user)) -> dict:
    del owner
    removed = _registry().remove(name)
    if not removed:
        raise HTTPException(status_code=404, detail="Service not found")
    return {"name": name, "removed": True}


@router.get("/model/diagnostics")
async def model_diagnostics(owner=Depends(_owner_user)) -> dict:
    del owner
    registry = _registry()
    endpoint = registry.resolve("amos://model") or _vault().get("AMOSCLAUD_MODEL_URL") or os.getenv("AMOSCLAUD_MODEL_URL", "http://model:8091")
    model = _vault().get("AMOSCLAUD_MODEL") or os.getenv("AMOSCLAUD_MODEL", "amosclaud-folder-v1")
    timeout = float(os.getenv("AMOSCLAUD_MODEL_TIMEOUT", "15"))
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(f"{endpoint.rstrip('/')}/api/tags")
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:
        return {"status": "unreachable", "endpoint": endpoint, "model": model, "detail": str(exc), "recommended_action": "Start or register the local Amosclaud model service, then retry."}
    available = [item.get("name", "") for item in payload.get("models", []) if isinstance(item, dict)]
    return {"status": "connected", "endpoint": endpoint, "model": model, "model_available": model in available, "available_models": available}


router.include_router(local_workspace.router)

from __future__ import annotations

import os
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

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


def _core_db_path() -> Path:
    return Path(os.getenv("AMOSCLAUD_CORE_DB", "/data/amosclaud-core.db"))


def _vault() -> AmosclaudVault:
    try:
        return AmosclaudVault(db_path=_core_db_path())
    except VaultError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _registry() -> ServiceRegistry:
    return ServiceRegistry(_core_db_path())


@router.get("/access")
def access_summary() -> dict:
    """Return only safe visibility information; never expose secrets or endpoints."""
    return AccessPolicy.from_environment().public_summary()


@router.get("/settings")
def list_settings(admin=Depends(_admin_user)) -> list[dict]:
    del admin
    return _vault().list_masked()


@router.put("/settings/{name}")
def set_setting(name: str, body: SettingWrite, admin=Depends(_admin_user)) -> dict:
    vault = _vault()
    vault.set(name, body.value, secret=body.secret, actor_id=int(admin["id"]))
    return {"name": name.strip().upper(), "saved": True, "is_secret": body.secret}


@router.delete("/settings/{name}")
def delete_setting(name: str, admin=Depends(_admin_user)) -> dict:
    deleted = _vault().delete(name, actor_id=int(admin["id"]))
    if not deleted:
        raise HTTPException(status_code=404, detail="Setting not found")
    return {"name": name.strip().upper(), "deleted": True}


@router.get("/services")
def list_services(admin=Depends(_admin_user)) -> list[dict]:
    del admin
    return _registry().list()


@router.put("/services/{name}")
def register_service(name: str, body: ServiceWrite, admin=Depends(_admin_user)) -> dict:
    del admin
    _registry().register(name, body.kind, body.endpoint, body.metadata)
    return {"name": name, "registered": True, "endpoint": body.endpoint}


@router.delete("/services/{name}")
def remove_service(name: str, admin=Depends(_admin_user)) -> dict:
    del admin
    removed = _registry().remove(name)
    if not removed:
        raise HTTPException(status_code=404, detail="Service not found")
    return {"name": name, "removed": True}


@router.get("/model/diagnostics")
async def model_diagnostics(admin=Depends(_admin_user)) -> dict:
    del admin
    registry = _registry()
    endpoint = registry.resolve("amos://model") or _vault().get("AMOSCLAUD_MODEL_URL") or os.getenv(
        "AMOSCLAUD_MODEL_URL", "http://model:11434"
    )
    model = _vault().get("AMOSCLAUD_MODEL") or os.getenv("AMOSCLAUD_MODEL", "qwen2.5-coder:3b")
    timeout = float(os.getenv("AMOSCLAUD_MODEL_TIMEOUT", "15"))
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(f"{endpoint.rstrip('/')}/api/tags")
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:
        return {
            "status": "unreachable",
            "endpoint": endpoint,
            "model": model,
            "detail": str(exc),
            "recommended_action": "Start or register the local Amosclaud model service, then retry.",
        }

    available = [item.get("name", "") for item in payload.get("models", []) if isinstance(item, dict)]
    return {
        "status": "connected",
        "endpoint": endpoint,
        "model": model,
        "model_available": model in available,
        "available_models": available,
    }

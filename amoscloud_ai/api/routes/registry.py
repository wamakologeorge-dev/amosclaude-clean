"""Discovery and administration API for the Amosclaud Registry."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from typing import Any, Literal
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel, Field, field_validator, model_validator

from amoscloud_ai import registry as registry_core
from amoscloud_ai.api.routes import admin as admin_routes

router = APIRouter(prefix="/registry", tags=["registry"])

TOKEN_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{1,79}$")
ENTRY_ID_PATTERN = r"^[a-z0-9][a-z0-9._-]{2,119}$"


def _db() -> sqlite3.Connection:
    db = admin_routes._db()
    registry_core.seed_builtin_entries(db)
    return db


def _validate_token_list(values: list[str], label: str) -> list[str]:
    cleaned = sorted({value.strip().lower() for value in values if value.strip()})
    if len(cleaned) > 100:
        raise ValueError(f"{label} supports at most 100 values")
    invalid = [value for value in cleaned if not TOKEN_PATTERN.fullmatch(value)]
    if invalid:
        raise ValueError(f"Invalid {label} value: {invalid[0]}")
    return cleaned


def _validate_entrypoint(value: str) -> str:
    cleaned = value.strip()
    if not cleaned or len(cleaned) > 500:
        raise ValueError("entrypoint is required and limited to 500 characters")
    parsed = urlparse(cleaned)
    if parsed.scheme:
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("URL entrypoints must use HTTPS")
        return cleaned
    normalized = cleaned.replace("\\", "/")
    if normalized.startswith("/"):
        if not normalized.startswith("/api/"):
            raise ValueError("Absolute entrypoints are limited to Amosclaud API paths")
        return normalized
    if ".." in normalized.split("/"):
        raise ValueError("entrypoint cannot contain '..' traversal")
    return normalized


def _validate_source_url(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    cleaned = value.strip()
    parsed = urlparse(cleaned)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("source_url must use HTTPS")
    return cleaned


class RegistryEntryCreate(BaseModel):
    id: str = Field(..., pattern=ENTRY_ID_PATTERN)
    kind: Literal["capability", "client", "service", "skill", "adapter"]
    title: str = Field(..., min_length=2, max_length=120)
    description: str = Field(..., min_length=10, max_length=1000)
    version: str = Field(..., min_length=1, max_length=64)
    status: Literal["active", "experimental", "deprecated"] = "experimental"
    trust: Literal["approved", "community"] = "community"
    entrypoint: str = Field(..., min_length=1, max_length=500)
    source_url: str | None = Field(default=None, max_length=500)
    capabilities: list[str] = Field(default_factory=list)
    platforms: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("entrypoint")
    @classmethod
    def validate_entrypoint(cls, value: str) -> str:
        return _validate_entrypoint(value)

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, value: str | None) -> str | None:
        return _validate_source_url(value)

    @field_validator("capabilities")
    @classmethod
    def validate_capabilities(cls, values: list[str]) -> list[str]:
        return _validate_token_list(values, "capability")

    @field_validator("platforms")
    @classmethod
    def validate_platforms(cls, values: list[str]) -> list[str]:
        return _validate_token_list(values, "platform")

    @model_validator(mode="after")
    def validate_metadata_size(self) -> "RegistryEntryCreate":
        if len(json.dumps(self.metadata, sort_keys=True, default=str)) > 16_000:
            raise ValueError("metadata is limited to 16,000 serialized characters")
        return self


class RegistryEntryUpdate(BaseModel):
    kind: Literal["capability", "client", "service", "skill", "adapter"] | None = None
    title: str | None = Field(default=None, min_length=2, max_length=120)
    description: str | None = Field(default=None, min_length=10, max_length=1000)
    version: str | None = Field(default=None, min_length=1, max_length=64)
    status: Literal["active", "experimental", "deprecated", "disabled"] | None = None
    trust: Literal["approved", "community"] | None = None
    entrypoint: str | None = Field(default=None, min_length=1, max_length=500)
    source_url: str | None = Field(default=None, max_length=500)
    capabilities: list[str] | None = None
    platforms: list[str] | None = None
    metadata: dict[str, Any] | None = None

    @field_validator("entrypoint")
    @classmethod
    def validate_entrypoint(cls, value: str | None) -> str | None:
        return _validate_entrypoint(value) if value is not None else None

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, value: str | None) -> str | None:
        return _validate_source_url(value)

    @field_validator("capabilities")
    @classmethod
    def validate_capabilities(cls, values: list[str] | None) -> list[str] | None:
        return _validate_token_list(values, "capability") if values is not None else None

    @field_validator("platforms")
    @classmethod
    def validate_platforms(cls, values: list[str] | None) -> list[str] | None:
        return _validate_token_list(values, "platform") if values is not None else None

    @model_validator(mode="after")
    def validate_update(self) -> "RegistryEntryUpdate":
        supplied = self.model_dump(exclude_none=True)
        if not supplied:
            raise ValueError("At least one registry field must be supplied")
        if (
            self.metadata is not None
            and len(json.dumps(self.metadata, sort_keys=True, default=str)) > 16_000
        ):
            raise ValueError("metadata is limited to 16,000 serialized characters")
        return self


@router.get("", summary="Get the Amosclaud Registry summary")
def registry_summary() -> dict[str, Any]:
    with _db() as db:
        summary = registry_core.registry_summary(db)
    summary["endpoints"] = {
        "entries": "/api/v1/registry/entries",
        "capabilities": "/api/v1/registry/capabilities",
        "manifest": "/api/v1/registry/manifest",
    }
    return summary


@router.get("/entries", summary="Discover Amosclaud Registry entries")
def list_registry_entries(
    kind: Literal["capability", "client", "service", "skill", "adapter"] | None = None,
    status_filter: Literal["active", "experimental", "deprecated"] | None = Query(
        default=None, alias="status"
    ),
    capability: str | None = Query(default=None, max_length=80),
    platform: str | None = Query(default=None, max_length=80),
) -> dict[str, Any]:
    with _db() as db:
        entries = registry_core.list_entries(
            db,
            kind=kind,
            status=status_filter,
            capability=capability.strip().lower() if capability else None,
            platform=platform.strip().lower() if platform else None,
        )
    return {"entries": entries, "count": len(entries)}


@router.get("/entries/{entry_id}", summary="Get one Amosclaud Registry entry")
def get_registry_entry(
    entry_id: str = Path(..., pattern=ENTRY_ID_PATTERN),
) -> dict[str, Any]:
    with _db() as db:
        entry = registry_core.get_entry(db, entry_id)
    if not entry or entry["status"] == "disabled":
        raise HTTPException(status_code=404, detail="Registry entry not found")
    return entry


@router.get("/capabilities", summary="List capabilities exposed by active registry entries")
def list_registry_capabilities() -> dict[str, Any]:
    with _db() as db:
        entries = registry_core.list_entries(db)
    providers: dict[str, list[str]] = {}
    for entry in entries:
        for capability in entry["capabilities"]:
            providers.setdefault(capability, []).append(entry["id"])
    return {
        "capabilities": [
            {"name": name, "providers": sorted(set(entry_ids))}
            for name, entry_ids in sorted(providers.items())
        ],
        "count": len(providers),
    }


@router.get("/manifest", summary="Get the immutable first-party Registry manifest")
def registry_manifest() -> dict[str, Any]:
    with _db() as db:
        entries = [entry for entry in registry_core.list_entries(db) if entry["immutable"]]
    digest_source = "\n".join(sorted(entry["manifest_digest"] for entry in entries))
    manifest_digest = hashlib.sha256(digest_source.encode("utf-8")).hexdigest()
    return {
        "schema_version": registry_core.REGISTRY_SCHEMA_VERSION,
        "identity": {"name": "Amosclaud Autonomous", "type": "one-agent"},
        "entries": entries,
        "count": len(entries),
        "manifest_digest": manifest_digest,
        "digest_scope": "registry metadata only; not an executable artifact signature",
    }


@router.post(
    "/entries",
    status_code=status.HTTP_201_CREATED,
    summary="Register an approved or community Amosclaud component",
)
def create_registry_entry(
    body: RegistryEntryCreate,
    admin: sqlite3.Row = Depends(admin_routes._admin_user),
) -> dict[str, Any]:
    with _db() as db:
        try:
            entry = registry_core.create_entry(db, body.model_dump(), created_by=int(admin["id"]))
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        admin_routes._audit(
            db,
            int(admin["id"]),
            "registry.create",
            "registry_entry",
            body.id,
            f"kind={body.kind};trust={body.trust};status={body.status}",
        )
        db.commit()
    return entry


@router.patch("/entries/{entry_id}", summary="Update a mutable Amosclaud Registry entry")
def update_registry_entry(
    body: RegistryEntryUpdate,
    entry_id: str = Path(..., pattern=ENTRY_ID_PATTERN),
    admin: sqlite3.Row = Depends(admin_routes._admin_user),
) -> dict[str, Any]:
    with _db() as db:
        try:
            entry = registry_core.update_entry(db, entry_id, body.model_dump(exclude_none=True))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Registry entry not found") from exc
        except PermissionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        admin_routes._audit(
            db,
            int(admin["id"]),
            "registry.update",
            "registry_entry",
            entry_id,
            f"fields={','.join(sorted(body.model_dump(exclude_none=True)))}",
        )
        db.commit()
    return entry


@router.delete("/entries/{entry_id}", summary="Disable a mutable Amosclaud Registry entry")
def disable_registry_entry(
    entry_id: str = Path(..., pattern=ENTRY_ID_PATTERN),
    admin: sqlite3.Row = Depends(admin_routes._admin_user),
) -> dict[str, Any]:
    with _db() as db:
        try:
            entry = registry_core.disable_entry(db, entry_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Registry entry not found") from exc
        except PermissionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        admin_routes._audit(
            db,
            int(admin["id"]),
            "registry.disable",
            "registry_entry",
            entry_id,
            "status=disabled",
        )
        db.commit()
    return entry

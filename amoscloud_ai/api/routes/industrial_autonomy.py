"""Authenticated API surface for Amosclaud SentinelGrid."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from amoscloud_ai.api.routes.auth import get_user_from_session
from amoscloud_ai.api.routes.pr_tasks import _require_owner_key
from amoscloud_ai.industrial_autonomy import (
    ActionNotFoundError,
    AssetNotFoundError,
    AssetType,
    SentinelGridControlPlane,
    StateConflictError,
)

router = APIRouter(prefix="/sentinel-grid", tags=["sentinel-grid"])
control_plane = SentinelGridControlPlane()


class AssetRegistration(BaseModel):
    name: str = Field(..., min_length=2, max_length=160)
    asset_type: AssetType
    site: str = Field(..., min_length=2, max_length=160)
    capabilities: list[str] = Field(default_factory=list, max_length=32)


class TelemetrySubmission(BaseModel):
    asset_id: str = Field(..., min_length=8, max_length=80)
    metrics: dict[str, float | int | bool | str] = Field(
        ...,
        min_length=1,
        max_length=64,
    )
    observed_at: datetime | None = None


class ActionProposalRequest(BaseModel):
    asset_id: str = Field(..., min_length=8, max_length=80)
    action_type: str = Field(..., min_length=2, max_length=80)
    reason: str = Field(..., min_length=3, max_length=2000)
    requested_by: str = Field(
        default="amosclaud-autonomous",
        min_length=2,
        max_length=160,
    )


class ActionDecisionRequest(BaseModel):
    decided_by: str = Field(..., min_length=2, max_length=160)
    note: str = Field(default="", max_length=2000)


def _authorise(request: Request, owner_key: Optional[str]) -> None:
    if owner_key:
        _require_owner_key(owner_key)
        return

    user = get_user_from_session(request.cookies.get("amos_session"))
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Sign in or provide the Amosclaud owner key.",
        )
    if not bool(user["is_admin"]):
        raise HTTPException(
            status_code=403,
            detail="Administrator approval is required for SentinelGrid operations.",
        )


def _translate_error(exc: Exception) -> HTTPException:
    if isinstance(exc, (AssetNotFoundError, ActionNotFoundError)):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, StateConflictError):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(
        status_code=500,
        detail="SentinelGrid could not complete the request",
    )


@router.get("")
def sentinel_grid_status() -> dict:
    """Return the public, secret-free SentinelGrid capability summary."""

    return control_plane.status()


@router.get("/assets")
def list_assets(
    request: Request,
    x_amosclaud_owner_key: Optional[str] = Header(default=None),
) -> list[dict]:
    _authorise(request, x_amosclaud_owner_key)
    return [asdict(item) for item in control_plane.list_assets()]


@router.post("/assets", status_code=201)
def register_asset(
    body: AssetRegistration,
    request: Request,
    x_amosclaud_owner_key: Optional[str] = Header(default=None),
) -> dict:
    _authorise(request, x_amosclaud_owner_key)
    asset = control_plane.register_asset(
        name=body.name,
        asset_type=body.asset_type,
        site=body.site,
        capabilities=tuple(body.capabilities),
    )
    return asdict(asset)


@router.post("/telemetry", status_code=202)
def ingest_telemetry(
    body: TelemetrySubmission,
    request: Request,
    x_amosclaud_owner_key: Optional[str] = Header(default=None),
) -> dict:
    _authorise(request, x_amosclaud_owner_key)
    try:
        telemetry, incidents = control_plane.record_telemetry(
            asset_id=body.asset_id,
            metrics=body.metrics,
            observed_at=body.observed_at,
        )
    except Exception as exc:
        raise _translate_error(exc) from exc
    return {
        "telemetry": asdict(telemetry),
        "incidents": [asdict(item) for item in incidents],
    }


@router.get("/incidents")
def list_incidents(
    request: Request,
    x_amosclaud_owner_key: Optional[str] = Header(default=None),
) -> list[dict]:
    _authorise(request, x_amosclaud_owner_key)
    return [asdict(item) for item in control_plane.list_incidents()]


@router.post("/actions", status_code=202)
def propose_action(
    body: ActionProposalRequest,
    request: Request,
    x_amosclaud_owner_key: Optional[str] = Header(default=None),
) -> dict:
    _authorise(request, x_amosclaud_owner_key)
    try:
        action = control_plane.propose_action(
            asset_id=body.asset_id,
            action_type=body.action_type,
            reason=body.reason,
            requested_by=body.requested_by,
        )
    except Exception as exc:
        raise _translate_error(exc) from exc
    return asdict(action)


@router.get("/actions")
def list_actions(
    request: Request,
    x_amosclaud_owner_key: Optional[str] = Header(default=None),
) -> list[dict]:
    _authorise(request, x_amosclaud_owner_key)
    return [asdict(item) for item in control_plane.list_actions()]


@router.post("/actions/{action_id}/approve")
def approve_action(
    action_id: str,
    body: ActionDecisionRequest,
    request: Request,
    x_amosclaud_owner_key: Optional[str] = Header(default=None),
) -> dict:
    _authorise(request, x_amosclaud_owner_key)
    try:
        action = control_plane.approve_action(
            action_id,
            decided_by=body.decided_by,
            decision_note=body.note,
        )
    except Exception as exc:
        raise _translate_error(exc) from exc
    return asdict(action)


@router.post("/actions/{action_id}/reject")
def reject_action(
    action_id: str,
    body: ActionDecisionRequest,
    request: Request,
    x_amosclaud_owner_key: Optional[str] = Header(default=None),
) -> dict:
    _authorise(request, x_amosclaud_owner_key)
    try:
        action = control_plane.reject_action(
            action_id,
            decided_by=body.decided_by,
            decision_note=body.note,
        )
    except Exception as exc:
        raise _translate_error(exc) from exc
    return asdict(action)

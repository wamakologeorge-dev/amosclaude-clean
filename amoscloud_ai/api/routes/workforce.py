"""Authenticated Autonomous Engineering Workforce and Asset Dashboard APIs."""

from __future__ import annotations

import sqlite3
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Cookie, Header, HTTPException, Query
from pydantic import BaseModel, Field

from amoscloud_ai.api.routes import task_router
from amoscloud_ai.engineering_workforce import (
    ASSET_ENVIRONMENTS,
    ASSET_TYPES,
    DELEGATION_KINDS,
    WorkforcePolicyError,
    add_delegation_event,
    asset_dict,
    authenticate_asset,
    build_delegation_objective,
    create_asset_token,
    delegation_dict,
    delegation_plan,
    ensure_guardrails,
    ensure_workforce_schema,
    execution_fabric,
    guardrail_dict,
    guardrail_snapshot,
    imported_repository,
    redact,
    select_execution_target,
    update_guardrails,
    validate_target_url,
    workforce_overview,
    _json,
    _now,
)

router = APIRouter(prefix="/workforce", tags=["autonomous-engineering-workforce"])


class DelegationCreate(BaseModel):
    repository: str = Field(min_length=3, max_length=300)
    kind: Literal["epic", "feature", "bug", "refactor", "maintenance", "requirement"]
    title: str = Field(min_length=3, max_length=200)
    requirement: str = Field(min_length=10, max_length=20_000)
    source_reference: str | None = Field(default=None, max_length=500)
    acceptance_criteria: list[str] = Field(min_length=1, max_length=30)
    mode: Literal["build", "fix", "test", "review"] = "build"
    execution_preference: Literal["auto", "edge", "cloud", "github"] = "auto"
    authorize_changes: bool = False


class GuardrailUpdate(BaseModel):
    allowed_paths: list[str] = Field(min_length=1, max_length=50)
    protected_paths: list[str] = Field(default_factory=list, max_length=100)
    protected_branches: list[str] = Field(min_length=1, max_length=30)
    branch_prefix: str = Field(default="amosclaud/workforce", min_length=3, max_length=80)
    max_repair_attempts: int = Field(default=3, ge=1, le=3)


class AssetCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    repository: str | None = Field(default=None, max_length=300)
    asset_type: Literal["service", "micro_saas", "data_pipeline", "agent", "library", "website"]
    environment: Literal["development", "staging", "production"] = "production"
    target_url: str | None = Field(default=None, max_length=1_000)
    license_reference: str | None = Field(default=None, max_length=500)
    transfer_notes: str | None = Field(default=None, max_length=5_000)


class AssetTelemetry(BaseModel):
    observed_at: str | None = Field(default=None, max_length=100)
    online: bool
    status_code: int | None = Field(default=None, ge=100, le=599)
    latency_ms: float | None = Field(default=None, ge=0, le=3_600_000)
    cpu_percent: float | None = Field(default=None, ge=0, le=100)
    memory_mb: float | None = Field(default=None, ge=0, le=10_000_000)
    error_count: int = Field(default=0, ge=0, le=1_000_000_000)
    request_count: int = Field(default=0, ge=0, le=1_000_000_000_000)
    active_users: int | None = Field(default=None, ge=0, le=1_000_000_000)
    revenue_usd: float | None = Field(default=None, ge=0, le=1_000_000_000_000)
    patch_success_count: int | None = Field(default=None, ge=0, le=1_000_000_000)
    patch_failure_count: int | None = Field(default=None, ge=0, le=1_000_000_000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AssetEventCreate(BaseModel):
    severity: Literal["info", "warning", "error", "critical"] = "info"
    event_type: str = Field(min_length=2, max_length=100)
    message: str = Field(min_length=1, max_length=8_000)
    details: dict[str, Any] = Field(default_factory=dict)


def _actor(session: str | None, authorization: str | None) -> int:
    return task_router._actor(session, authorization)


def _owned_delegation(db: sqlite3.Connection, delegation_id: str, user_id: int):
    row = db.execute(
        "SELECT * FROM workforce_delegations WHERE id=? AND user_id=?",
        (delegation_id, user_id),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Workforce delegation not found")
    return row


def _owned_asset(db: sqlite3.Connection, asset_id: str, user_id: int):
    row = db.execute(
        "SELECT * FROM software_assets WHERE id=? AND user_id=?",
        (asset_id, user_id),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Software asset not found")
    return row


def _repository_for_user(db: sqlite3.Connection, user_id: int, value: str | None):
    repository = str(value or "").strip()
    if not repository:
        return None
    row = db.execute(
        """SELECT * FROM repositories
           WHERE owner_id=? AND (github_full_name=? COLLATE NOCASE OR name=? COLLATE NOCASE)
           ORDER BY github_full_name IS NOT NULL DESC LIMIT 1""",
        (user_id, repository, repository),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Repository is not available in this Amosclaud account")
    return row


def _clean_criteria(values: list[str]) -> list[str]:
    criteria = [" ".join(str(value).split()) for value in values if str(value).strip()]
    if not criteria:
        raise HTTPException(status_code=422, detail="Add at least one acceptance criterion")
    return criteria


@router.get("/overview")
def get_workforce_overview(
    amos_session: str | None = Cookie(default=None),
    authorization: str | None = Header(default=None),
) -> dict:
    user_id = _actor(amos_session, authorization)
    with task_router._connect() as db:
        return workforce_overview(db, user_id)


@router.get("/execution-fabric")
def get_execution_fabric(
    mode: Literal["build", "fix", "test", "review"] = "build",
    amos_session: str | None = Cookie(default=None),
    authorization: str | None = Header(default=None),
) -> dict:
    user_id = _actor(amos_session, authorization)
    with task_router._connect() as db:
        return execution_fabric(db, user_id, mode)


@router.get("/guardrails")
def get_guardrails(
    amos_session: str | None = Cookie(default=None),
    authorization: str | None = Header(default=None),
) -> dict:
    user_id = _actor(amos_session, authorization)
    with task_router._connect() as db:
        return guardrail_dict(ensure_guardrails(db, user_id))


@router.put("/guardrails")
def put_guardrails(
    body: GuardrailUpdate,
    amos_session: str | None = Cookie(default=None),
    authorization: str | None = Header(default=None),
) -> dict:
    user_id = _actor(amos_session, authorization)
    try:
        with task_router._connect() as db:
            row = update_guardrails(
                db,
                user_id,
                allowed_paths=body.allowed_paths,
                protected_paths=body.protected_paths,
                protected_branches=body.protected_branches,
                branch_prefix=body.branch_prefix,
                max_repair_attempts=body.max_repair_attempts,
            )
            return guardrail_dict(row)
    except WorkforcePolicyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/delegations", status_code=202)
def create_delegation(
    body: DelegationCreate,
    amos_session: str | None = Cookie(default=None),
    authorization: str | None = Header(default=None),
) -> dict:
    user_id = _actor(amos_session, authorization)
    if body.kind not in DELEGATION_KINDS:
        raise HTTPException(status_code=422, detail="Unsupported delegation type")
    repository = body.repository.strip()
    criteria = _clean_criteria(body.acceptance_criteria)
    delegation_id = "work_" + uuid.uuid4().hex
    writes_repository = body.mode in {"build", "fix"}

    try:
        with task_router._connect() as db:
            ensure_workforce_schema(db, commit=False)
            if not imported_repository(db, user_id, repository):
                raise HTTPException(
                    status_code=404,
                    detail=(
                        "Import this connected GitHub repository before delegating code changes. "
                        "Native Amosclaud repository delegation will use a separate native branch adapter."
                    ),
                )
            guardrail_row = ensure_guardrails(db, user_id, commit=False)
            guardrails = guardrail_snapshot(guardrail_row)
            execution_target, runner_id, scheduler_reason = select_execution_target(
                db,
                user_id,
                mode=body.mode,
                preference=body.execution_preference,
            )
            plan = delegation_plan(body.kind, criteria)
            status = (
                "awaiting_approval"
                if writes_repository and not body.authorize_changes
                else "planning"
            )
            now = _now()
            db.execute(
                """INSERT INTO workforce_delegations(
                       id,user_id,repository,kind,title,requirement,source_reference,
                       acceptance_criteria_json,execution_preference,execution_target,
                       runner_id,status,guardrails_json,plan_json,created_at,updated_at
                   ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    delegation_id,
                    user_id,
                    repository,
                    body.kind,
                    body.title.strip(),
                    body.requirement.strip(),
                    body.source_reference,
                    _json(criteria),
                    body.execution_preference,
                    execution_target,
                    runner_id,
                    status,
                    _json(guardrails),
                    _json(plan),
                    now,
                    now,
                ),
            )
            add_delegation_event(
                db,
                delegation_id,
                "delegation.accepted",
                "Amosclaud accepted the complete engineering delegation.",
                {
                    "scheduler_reason": scheduler_reason,
                    "execution_target": execution_target,
                    "runner_id": runner_id,
                    "changes_authorized": body.authorize_changes,
                },
            )
            db.commit()

        objective = build_delegation_objective(
            delegation_id=delegation_id,
            kind=body.kind,
            title=body.title.strip(),
            requirement=body.requirement,
            source_reference=body.source_reference,
            acceptance_criteria=criteria,
            guardrails=guardrails,
        )
        require_approval = writes_repository and not body.authorize_changes
        task = task_router.create_task(
            task_router.TaskCreate(
                objective=objective,
                repository=repository,
                mode=body.mode,
                delivery="pull_request" if writes_repository else "report",
                runner_id=runner_id,
                execution_target=execution_target,
                require_approval=require_approval,
                metadata={
                    "engineering_workforce": True,
                    "single_brain": True,
                    "delegation_id": delegation_id,
                    "delegation_kind": body.kind,
                    "source_reference": body.source_reference,
                    "notification_policy": "human_judgment_or_final_signoff_only",
                    **guardrails,
                },
            ),
            amos_session=amos_session,
            authorization=authorization,
        )
    except WorkforcePolicyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except HTTPException:
        with task_router._connect() as db:
            ensure_workforce_schema(db, commit=False)
            db.execute(
                "UPDATE workforce_delegations SET status='blocked',updated_at=? WHERE id=?",
                (_now(), delegation_id),
            )
            add_delegation_event(
                db,
                delegation_id,
                "delegation.blocked",
                "The delegation could not enter the execution queue.",
            )
            db.commit()
        raise

    with task_router._connect() as db:
        ensure_workforce_schema(db, commit=False)
        db.execute(
            """UPDATE workforce_delegations
               SET task_id=?,status=?,updated_at=? WHERE id=?""",
            (task["id"], task["status"], _now(), delegation_id),
        )
        add_delegation_event(
            db,
            delegation_id,
            "task.created",
            "The delegation entered the durable Global Task Router.",
            {
                "task_id": task["id"],
                "status": task["status"],
                "execution_target": task["execution_target"],
            },
        )
        db.commit()
        row = _owned_delegation(db, delegation_id, user_id)
        return delegation_dict(db, row)


@router.get("/delegations")
def list_delegations(
    limit: int = Query(default=50, ge=1, le=200),
    amos_session: str | None = Cookie(default=None),
    authorization: str | None = Header(default=None),
) -> list[dict]:
    user_id = _actor(amos_session, authorization)
    with task_router._connect() as db:
        ensure_workforce_schema(db)
        rows = db.execute(
            """SELECT * FROM workforce_delegations
               WHERE user_id=? ORDER BY created_at DESC LIMIT ?""",
            (user_id, limit),
        ).fetchall()
        return [delegation_dict(db, row) for row in rows]


@router.get("/delegations/{delegation_id}")
def get_delegation(
    delegation_id: str,
    amos_session: str | None = Cookie(default=None),
    authorization: str | None = Header(default=None),
) -> dict:
    user_id = _actor(amos_session, authorization)
    with task_router._connect() as db:
        ensure_workforce_schema(db)
        row = _owned_delegation(db, delegation_id, user_id)
        result = delegation_dict(db, row)
        events = db.execute(
            """SELECT event_type,message,details_json,created_at
               FROM workforce_delegation_events
               WHERE delegation_id=? ORDER BY id""",
            (delegation_id,),
        ).fetchall()
        task_events = []
        if row["task_id"]:
            task_events = db.execute(
                """SELECT event_type,message,details_json,created_at
                   FROM global_task_events WHERE task_id=? ORDER BY id""",
                (row["task_id"],),
            ).fetchall()
        result["events"] = [
            {
                "event_type": event["event_type"],
                "message": event["message"],
                "details": task_router._loads(event["details_json"], {}),
                "created_at": event["created_at"],
            }
            for event in [*events, *task_events]
        ]
        result["events"].sort(key=lambda event: event["created_at"])
        return result


@router.post("/delegations/{delegation_id}/approve")
def approve_delegation(
    delegation_id: str,
    amos_session: str | None = Cookie(default=None),
    authorization: str | None = Header(default=None),
) -> dict:
    user_id = _actor(amos_session, authorization)
    with task_router._connect() as db:
        ensure_workforce_schema(db)
        row = _owned_delegation(db, delegation_id, user_id)
        if not row["task_id"]:
            raise HTTPException(status_code=409, detail="Delegation has no durable task")
        task_id = str(row["task_id"])
    task_router.approve_task(task_id, amos_session=amos_session, authorization=authorization)
    with task_router._connect() as db:
        ensure_workforce_schema(db, commit=False)
        db.execute(
            "UPDATE workforce_delegations SET status='queued',updated_at=? WHERE id=?",
            (_now(), delegation_id),
        )
        add_delegation_event(
            db,
            delegation_id,
            "delegation.approved",
            "Repository changes were explicitly authorized and execution was queued.",
        )
        db.commit()
        return delegation_dict(db, _owned_delegation(db, delegation_id, user_id))


@router.post("/delegations/{delegation_id}/cancel")
def cancel_delegation(
    delegation_id: str,
    amos_session: str | None = Cookie(default=None),
    authorization: str | None = Header(default=None),
) -> dict:
    user_id = _actor(amos_session, authorization)
    with task_router._connect() as db:
        ensure_workforce_schema(db)
        row = _owned_delegation(db, delegation_id, user_id)
        if not row["task_id"]:
            raise HTTPException(status_code=409, detail="Delegation has no durable task")
        task_id = str(row["task_id"])
    task_router.cancel_task(task_id, amos_session=amos_session, authorization=authorization)
    with task_router._connect() as db:
        ensure_workforce_schema(db, commit=False)
        db.execute(
            "UPDATE workforce_delegations SET status='cancelled',updated_at=? WHERE id=?",
            (_now(), delegation_id),
        )
        add_delegation_event(db, delegation_id, "delegation.cancelled", "Delegation cancelled before execution.")
        db.commit()
        return delegation_dict(db, _owned_delegation(db, delegation_id, user_id))


@router.post("/assets", status_code=201)
def create_asset(
    body: AssetCreate,
    amos_session: str | None = Cookie(default=None),
    authorization: str | None = Header(default=None),
) -> dict:
    user_id = _actor(amos_session, authorization)
    if body.asset_type not in ASSET_TYPES or body.environment not in ASSET_ENVIRONMENTS:
        raise HTTPException(status_code=422, detail="Unsupported asset configuration")
    try:
        target_url = validate_target_url(body.target_url)
    except WorkforcePolicyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    asset_id = "asset_" + uuid.uuid4().hex
    telemetry_token, token_hash, token_prefix = create_asset_token()
    now = _now()
    with task_router._connect() as db:
        ensure_workforce_schema(db, commit=False)
        repository_row = _repository_for_user(db, user_id, body.repository)
        repository = None
        if repository_row:
            repository = str(repository_row["github_full_name"] or repository_row["name"])
        db.execute(
            """INSERT INTO software_assets(
                   id,user_id,name,repository,asset_type,environment,target_url,
                   telemetry_token_hash,telemetry_token_prefix,license_reference,
                   transfer_notes,created_at,updated_at
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                asset_id,
                user_id,
                body.name.strip(),
                repository,
                body.asset_type,
                body.environment,
                target_url,
                token_hash,
                token_prefix,
                body.license_reference,
                redact(body.transfer_notes or "", 5_000) or None,
                now,
                now,
            ),
        )
        db.commit()
        row = _owned_asset(db, asset_id, user_id)
        result = asset_dict(db, row)
    result["telemetry_token"] = telemetry_token
    result["warning"] = "Copy this asset telemetry credential now. Amosclaud stores only its hash."
    return result


@router.get("/assets")
def list_assets(
    amos_session: str | None = Cookie(default=None),
    authorization: str | None = Header(default=None),
) -> list[dict]:
    user_id = _actor(amos_session, authorization)
    with task_router._connect() as db:
        ensure_workforce_schema(db)
        rows = db.execute(
            "SELECT * FROM software_assets WHERE user_id=? ORDER BY updated_at DESC",
            (user_id,),
        ).fetchall()
        return [asset_dict(db, row) for row in rows]


@router.get("/assets/{asset_id}")
def get_asset(
    asset_id: str,
    amos_session: str | None = Cookie(default=None),
    authorization: str | None = Header(default=None),
) -> dict:
    user_id = _actor(amos_session, authorization)
    with task_router._connect() as db:
        ensure_workforce_schema(db)
        row = _owned_asset(db, asset_id, user_id)
        result = asset_dict(db, row)
        result["events"] = [
            {
                **dict(event),
                "details": task_router._loads(event["details_json"], {}),
            }
            for event in db.execute(
                """SELECT id,severity,event_type,message,details_json,created_at
                   FROM software_asset_events WHERE asset_id=?
                   ORDER BY created_at DESC,id DESC LIMIT 100""",
                (asset_id,),
            ).fetchall()
        ]
        for event in result["events"]:
            event.pop("details_json", None)
        return result


@router.post("/assets/{asset_id}/telemetry", status_code=202)
def submit_asset_telemetry(
    asset_id: str,
    body: AssetTelemetry,
    authorization: str | None = Header(default=None),
) -> dict:
    try:
        with task_router._connect() as db:
            ensure_workforce_schema(db, commit=False)
            asset = authenticate_asset(db, asset_id, authorization)
            observed_at = body.observed_at or _now()
            revenue_cents = (
                int(round(body.revenue_usd * 100)) if body.revenue_usd is not None else None
            )
            db.execute(
                """INSERT INTO software_asset_telemetry(
                       asset_id,observed_at,online,status_code,latency_ms,cpu_percent,
                       memory_mb,error_count,request_count,active_users,revenue_cents,
                       patch_success_count,patch_failure_count,metadata_json
                   ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    asset_id,
                    observed_at,
                    int(body.online),
                    body.status_code,
                    body.latency_ms,
                    body.cpu_percent,
                    body.memory_mb,
                    body.error_count,
                    body.request_count,
                    body.active_users,
                    revenue_cents,
                    body.patch_success_count,
                    body.patch_failure_count,
                    _json(body.metadata),
                ),
            )
            db.execute(
                "UPDATE software_assets SET updated_at=? WHERE id=?",
                (_now(), asset_id),
            )
            db.commit()
            return {
                "accepted": True,
                "asset_id": asset_id,
                "state": asset_dict(db, asset)["health"]["state"],
            }
    except WorkforcePolicyError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@router.post("/assets/{asset_id}/events", status_code=202)
def submit_asset_event(
    asset_id: str,
    body: AssetEventCreate,
    authorization: str | None = Header(default=None),
) -> dict:
    try:
        with task_router._connect() as db:
            ensure_workforce_schema(db, commit=False)
            authenticate_asset(db, asset_id, authorization)
            db.execute(
                """INSERT INTO software_asset_events(
                       asset_id,severity,event_type,message,details_json,created_at
                   ) VALUES (?,?,?,?,?,?)""",
                (
                    asset_id,
                    body.severity,
                    body.event_type.strip(),
                    redact(body.message),
                    _json(body.details),
                    _now(),
                ),
            )
            db.execute("UPDATE software_assets SET updated_at=? WHERE id=?", (_now(), asset_id))
            db.commit()
        return {"accepted": True, "asset_id": asset_id}
    except WorkforcePolicyError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@router.post("/assets/{asset_id}/rotate-token")
def rotate_asset_token(
    asset_id: str,
    amos_session: str | None = Cookie(default=None),
    authorization: str | None = Header(default=None),
) -> dict:
    user_id = _actor(amos_session, authorization)
    token, token_hash, token_prefix = create_asset_token()
    with task_router._connect() as db:
        ensure_workforce_schema(db, commit=False)
        _owned_asset(db, asset_id, user_id)
        db.execute(
            """UPDATE software_assets SET telemetry_token_hash=?,telemetry_token_prefix=?,
                      updated_at=? WHERE id=?""",
            (token_hash, token_prefix, _now(), asset_id),
        )
        db.commit()
    return {
        "asset_id": asset_id,
        "telemetry_token": token,
        "warning": "The previous telemetry credential is now invalid. Copy this credential now.",
    }


@router.get("/assets/{asset_id}/manifest")
def asset_transfer_manifest(
    asset_id: str,
    amos_session: str | None = Cookie(default=None),
    authorization: str | None = Header(default=None),
) -> dict:
    user_id = _actor(amos_session, authorization)
    with task_router._connect() as db:
        ensure_workforce_schema(db)
        row = _owned_asset(db, asset_id, user_id)
        item = asset_dict(db, row)
    return {
        "manifest_version": 1,
        "asset": {
            key: item.get(key)
            for key in (
                "id",
                "name",
                "repository",
                "asset_type",
                "environment",
                "target_url",
                "lifecycle_status",
                "license_reference",
                "transfer_notes",
                "created_at",
                "updated_at",
            )
        },
        "health_snapshot": item["health"],
        "secrets_included": False,
        "transfer_rule": "Credentials and environment secrets must be re-authorized by the recipient.",
    }

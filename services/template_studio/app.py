"""FastAPI application for Amosclaud Template Studio."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .policy import (
    PolicyDrivenAssistant,
    TemplatePolicyError,
    clean_html,
    clean_kind,
    clean_metadata,
    clean_progress,
    clean_status,
    clean_title,
    template_catalog,
    template_content,
)
from .storage import PlanStore

SERVICE_ROOT = Path(__file__).resolve().parent
STATIC_ROOT = SERVICE_ROOT / "static"
DB_PATH = Path(os.getenv("TEMPLATE_STUDIO_DB", str(SERVICE_ROOT / "data" / "template-studio.db")))

store = PlanStore(DB_PATH)
assistant = PolicyDrivenAssistant()
app = FastAPI(
    title="Amosclaud Template Studio",
    version="1.0.0",
    description="Policy-driven project, business, marketing and management planning studio.",
)
app.mount("/assets", StaticFiles(directory=STATIC_ROOT), name="template-studio-assets")


class PlanCreate(BaseModel):
    title: str
    kind: str = "blank"
    owner: str = ""
    status: str = "draft"
    progress: int = Field(default=0, ge=0, le=100)
    content: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class PlanUpdate(BaseModel):
    title: str | None = None
    kind: str | None = None
    owner: str | None = None
    status: str | None = None
    progress: int | None = Field(default=None, ge=0, le=100)
    content: str | None = None
    metadata: dict[str, Any] | None = None


class TaskCreate(BaseModel):
    title: str
    status: str = "todo"
    priority: str = "medium"
    due_date: str | None = None
    position: int = 0


class TaskUpdate(BaseModel):
    title: str | None = None
    status: str | None = None
    priority: str | None = None
    due_date: str | None = None
    position: int | None = None


class AssistanceRequest(BaseModel):
    action: str
    selection: str = ""
    instruction: str = ""


class SnapshotRequest(BaseModel):
    reason: str = "manual"


def normalize_plan_payload(payload: PlanCreate) -> dict[str, Any]:
    title = clean_title(payload.title)
    kind = clean_kind(payload.kind)
    return {
        "title": title,
        "kind": kind,
        "owner": str(payload.owner or "")[:160],
        "status": clean_status(payload.status),
        "progress": clean_progress(payload.progress),
        "content": clean_html(payload.content or template_content(kind, title)),
        "metadata": clean_metadata(payload.metadata),
    }


def normalize_plan_changes(payload: PlanUpdate) -> dict[str, Any]:
    changes: dict[str, Any] = {}
    for key, value in payload.model_dump(exclude_unset=True).items():
        if key == "title": changes[key] = clean_title(str(value))
        elif key == "kind": changes[key] = clean_kind(str(value))
        elif key == "status": changes[key] = clean_status(str(value))
        elif key == "progress": changes[key] = clean_progress(value)
        elif key == "content": changes[key] = clean_html(str(value or ""))
        elif key == "metadata": changes[key] = clean_metadata(value)
        elif key == "owner": changes[key] = str(value or "")[:160]
    return changes


@app.exception_handler(TemplatePolicyError)
async def template_policy_error_handler(_request, exc: TemplatePolicyError):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.get("/", include_in_schema=False)
def studio_home() -> FileResponse:
    return FileResponse(STATIC_ROOT / "index.html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "template-studio"}


@app.get("/api/templates")
def get_templates() -> list[dict[str, Any]]:
    return template_catalog()


@app.get("/api/plans")
def list_plans(limit: int = 100) -> list[dict[str, Any]]:
    return store.list_plans(limit=limit)


@app.post("/api/plans", status_code=201)
def create_plan(payload: PlanCreate) -> dict[str, Any]:
    return store.create_plan(normalize_plan_payload(payload))


@app.get("/api/plans/{plan_id}")
def get_plan(plan_id: str) -> dict[str, Any]:
    plan = store.get_plan(plan_id)
    if plan is None: raise HTTPException(status_code=404, detail="Plan not found")
    return plan


@app.put("/api/plans/{plan_id}")
def update_plan(plan_id: str, payload: PlanUpdate) -> dict[str, Any]:
    plan = store.update_plan(plan_id, normalize_plan_changes(payload))
    if plan is None: raise HTTPException(status_code=404, detail="Plan not found")
    return plan


@app.delete("/api/plans/{plan_id}", status_code=204)
def delete_plan(plan_id: str) -> None:
    if not store.delete_plan(plan_id): raise HTTPException(status_code=404, detail="Plan not found")


@app.post("/api/plans/{plan_id}/versions", status_code=201)
def create_version(plan_id: str, payload: SnapshotRequest) -> dict[str, Any]:
    snapshot = store.snapshot(plan_id, reason=str(payload.reason or "manual")[:80])
    if snapshot is None: raise HTTPException(status_code=404, detail="Plan not found")
    return snapshot


@app.get("/api/plans/{plan_id}/versions")
def list_versions(plan_id: str) -> list[dict[str, Any]]:
    if store.get_plan(plan_id) is None: raise HTTPException(status_code=404, detail="Plan not found")
    return store.list_versions(plan_id)


@app.get("/api/plans/{plan_id}/versions/{version}")
def get_version(plan_id: str, version: int) -> dict[str, Any]:
    selected = store.get_version(plan_id, version)
    if selected is None: raise HTTPException(status_code=404, detail="Version not found")
    return selected


@app.post("/api/plans/{plan_id}/versions/{version}/restore")
def restore_version(plan_id: str, version: int) -> dict[str, Any]:
    plan = store.restore_version(plan_id, version)
    if plan is None: raise HTTPException(status_code=404, detail="Version not found")
    return plan


@app.get("/api/plans/{plan_id}/tasks")
def list_tasks(plan_id: str) -> list[dict[str, Any]]:
    if store.get_plan(plan_id) is None: raise HTTPException(status_code=404, detail="Plan not found")
    return store.list_tasks(plan_id)


@app.post("/api/plans/{plan_id}/tasks", status_code=201)
def create_task(plan_id: str, payload: TaskCreate) -> dict[str, Any]:
    try:
        task = store.create_task(plan_id, payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if task is None: raise HTTPException(status_code=404, detail="Plan not found")
    return task


@app.patch("/api/tasks/{task_id}")
def update_task(task_id: str, payload: TaskUpdate) -> dict[str, Any]:
    try:
        task = store.update_task(task_id, payload.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if task is None: raise HTTPException(status_code=404, detail="Task not found")
    return task


@app.delete("/api/tasks/{task_id}", status_code=204)
def delete_task(task_id: str) -> None:
    if not store.delete_task(task_id): raise HTTPException(status_code=404, detail="Task not found")


@app.post("/api/plans/{plan_id}/ai")
def assist_plan(plan_id: str, payload: AssistanceRequest) -> dict[str, Any]:
    plan = store.get_plan(plan_id)
    if plan is None: raise HTTPException(status_code=404, detail="Plan not found")
    result = assistant.assist(action=payload.action, plan=plan, selection=payload.selection, instruction=payload.instruction)
    return {"action": result.action, "title": result.title, "html": result.html, "policy": result.policy, "provider": result.provider}

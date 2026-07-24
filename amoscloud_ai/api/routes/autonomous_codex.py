"""Autonomous Codex configuration, skill discovery, and codex memory API."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from amoscloud_ai import codex_memory
from amoscloud_ai.api.routes.agent import _authenticated_user
from amoscloud_ai.autonomous_codex_config import (
    get_autonomous_codex_configuration,
    select_skill,
)

router = APIRouter(prefix="/autonomous-codex", tags=["autonomous-codex"])


def _require_user(request: Request):
    user = _authenticated_user(request)
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Sign in or provide a valid Amosclaud Autonomous bearer key",
        )
    return user


@router.get("/configuration", summary="Get safe autonomous agent configuration")
async def configuration(request: Request) -> dict:
    _require_user(request)
    return get_autonomous_codex_configuration().public_dict()


@router.get("/skills", summary="List autonomous skills")
async def skills(request: Request) -> dict:
    _require_user(request)
    config = get_autonomous_codex_configuration()
    return {
        "default_skill": config.default_skill,
        "skills": [
            {
                "name": skill.name,
                "title": skill.title,
                "mission": skill.mission,
                "phases": list(skill.phases),
                "tools": list(skill.tools),
                "default_write_policy": skill.default_write_policy,
            }
            for skill in config.skills
        ],
    }


@router.get("/tools", summary="List controlled autonomous tools")
async def tools(request: Request) -> dict:
    _require_user(request)
    config = get_autonomous_codex_configuration()
    return {
        "tools": [
            {
                "name": tool.name,
                "description": tool.description,
                "category": tool.category,
                "write_capable": tool.write_capable,
                "approval_required": tool.approval_required,
                "enabled": tool.enabled,
            }
            for tool in config.tools
        ]
    }


@router.get("/memory", summary="Search or browse the agent codex memory")
async def memory_search(
    request: Request,
    query: str | None = None,
    scope: str | None = None,
    kind: str | None = None,
    limit: int = 20,
) -> dict:
    _require_user(request)
    try:
        if query and query.strip():
            entries = codex_memory.search(
                query,
                scope=scope,
                kinds=[kind] if kind else None,
                limit=limit,
            )
        else:
            entries = codex_memory.recent(scope=scope, limit=limit)
            if kind:
                wanted = codex_memory.normalise_kind(kind)
                entries = [entry for entry in entries if entry.get("kind") == wanted]
    except codex_memory.CodexMemoryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"entries": entries, "count": len(entries)}


@router.post("/memory", summary="Store a codex memory entry")
async def memory_store(request: Request, body: dict) -> dict:
    _require_user(request)
    try:
        entry = codex_memory.store_entry(
            scope=body.get("scope"),
            kind=str(body.get("kind") or ""),
            title=str(body.get("title") or ""),
            content=str(body.get("content") or ""),
            tags=[str(tag) for tag in (body.get("tags") or []) if str(tag).strip()],
            importance=float(body.get("importance", 0.5)),
            source=str(body.get("source") or "") or None,
            outcome=str(body.get("outcome") or "unknown"),
        )
    except codex_memory.CodexMemoryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"stored": True, "entry": entry}


@router.get("/memory/volumes", summary="List codex memory volumes")
async def memory_volumes(request: Request) -> dict:
    _require_user(request)
    return {"volumes": codex_memory.volumes()}


@router.get("/memory/digest", summary="Get a chaptered codex digest for a volume")
async def memory_digest(
    request: Request, scope: str | None = None, per_chapter: int = 6
) -> dict:
    _require_user(request)
    return codex_memory.digest(scope, per_chapter=per_chapter)


@router.get("/memory/stats", summary="Codex memory statistics")
async def memory_stats(request: Request) -> dict:
    _require_user(request)
    return codex_memory.stats()


@router.post("/select-skill", summary="Resolve the skill for an objective")
async def resolve_skill(request: Request, body: dict) -> dict:
    _require_user(request)
    objective = str(body.get("objective") or "").strip()
    if not objective:
        raise HTTPException(status_code=422, detail="objective is required")
    try:
        skill = select_skill(objective, body.get("skill"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "skill": skill.name,
        "title": skill.title,
        "phases": list(skill.phases),
        "tools": list(skill.tools),
        "write_policy": skill.default_write_policy,
    }

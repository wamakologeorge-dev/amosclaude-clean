"""Autonomous Codex configuration and skill discovery API."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

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

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Cookie, Depends, HTTPException
from pydantic import BaseModel, Field

from amoscloud_ai.amo_lang import AmoRuntime, AmoSyntaxError, parse_amo
from amoscloud_ai.api.routes.auth import get_user_from_session
from amoscloud_ai.api.routes.core import _owner_user
from amoscloud_ai.core.command_agent import AgentCommandError, AmosclaudCommandAgent
from amoscloud_ai.core.workspace import WorkspaceError

router = APIRouter(prefix="/amo", tags=["amo-runtime"])


class AmoRunRequest(BaseModel):
    source: str = Field(min_length=1, max_length=200_000)
    input: str = Field(default="", max_length=100_000)


class CommandRequest(BaseModel):
    instruction: str = Field(min_length=1, max_length=20_000)
    execute: bool = False
    confirmed_actions: list[str] = Field(default_factory=list, max_length=20)


def _current_user(amos_session: str | None = Cookie(default=None)) -> sqlite3.Row:
    user = get_user_from_session(amos_session)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


@router.post("/run")
def run_amo(body: AmoRunRequest, user: sqlite3.Row = Depends(_current_user)) -> dict:
    try:
        program = parse_amo(body.source)
        result = AmoRuntime().execute(program, input_text=body.input)
        result["user_id"] = int(user["id"])
        return result
    except AmoSyntaxError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except WorkspaceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/compile")
def compile_amo(body: AmoRunRequest, user: sqlite3.Row = Depends(_current_user)) -> dict:
    del user
    try:
        return parse_amo(body.source).to_dict()
    except AmoSyntaxError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/command/plan")
def plan_command(body: CommandRequest, owner=Depends(_owner_user)) -> dict:
    del owner
    try:
        return AmosclaudCommandAgent().plan(body.instruction).to_dict()
    except AgentCommandError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/command/run")
def run_command(body: CommandRequest, owner=Depends(_owner_user)) -> dict:
    del owner
    try:
        agent = AmosclaudCommandAgent()
        plan = agent.plan(body.instruction)
        if not body.execute:
            return {"status": "planned", "plan": plan.to_dict()}
        return agent.execute(plan, confirmed_actions=set(body.confirmed_actions))
    except AgentCommandError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

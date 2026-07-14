from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from amoscloud_ai.api.routes.core import _owner_user
from amoscloud_ai.core.command_agent import AgentCommandError, AmosclaudCommandAgent

router = APIRouter(prefix="/command-agent", tags=["command-agent"])


class CommandRequest(BaseModel):
    instruction: str = Field(min_length=1, max_length=20000)
    execute: bool = False
    confirmed_actions: list[str] = Field(default_factory=list, max_length=20)


@router.post("/plan")
def plan_command(body: CommandRequest, owner=Depends(_owner_user)) -> dict:
    del owner
    try:
        return AmosclaudCommandAgent().plan(body.instruction).to_dict()
    except AgentCommandError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/run")
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

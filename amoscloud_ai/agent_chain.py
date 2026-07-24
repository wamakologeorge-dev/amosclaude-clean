"""Canonical authentication and skill-routing chain for Amosclaud agents."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, Request

from amoscloud_ai.api.routes.auth import get_user_from_session
from amoscloud_ai.api.routes.autonomous_keys import (
    authenticate_autonomous_key,
    autonomous_key_skills,
)

MODE_SKILLS = {
    "autonomous-check": "inspect",
    "answer": "answer",
    "guide": "answer",
    "plan": "plan",
    "build": "build",
    "fix": "fix",
    "test": "test",
    "deploy": "deploy",
    "monitor": "monitor",
}


@dataclass(frozen=True)
class AgentChainContext:
    """Identity and permissions resolved by the single agent power chain."""

    user: Any
    authentication: str
    skills: frozenset[str]
    requested_mode: str
    required_skill: str

    @property
    def user_id(self) -> int:
        return int(self.user["id"])

    def metadata(self) -> dict[str, Any]:
        return {
            "agent_chain": "amosclaud-agent-power-chain-v1",
            "agent_chain_route": "/api/v1/agent-chain/run",
            "authenticated_user_id": self.user_id,
            "authentication": self.authentication,
            "authorized_skills": sorted(self.skills),
            "required_skill": self.required_skill,
        }


class AgentPowerChain:
    """Resolve identity, enforce key skills, and produce one runtime context."""

    route = "/api/v1/agent-chain/run"

    @staticmethod
    def bearer_token(request: Request) -> str | None:
        authorization = request.headers.get("authorization", "").strip()
        scheme, separator, value = authorization.partition(" ")
        if separator and scheme.lower() == "bearer" and value.strip():
            return value.strip()
        return None

    def authenticate(self, request: Request) -> tuple[Any, str, frozenset[str]]:
        session_user = get_user_from_session(request.cookies.get("amos_session"))
        if session_user:
            return session_user, "session", frozenset(MODE_SKILLS.values())

        key_user = authenticate_autonomous_key(self.bearer_token(request))
        if key_user:
            return key_user, "autonomous-key", autonomous_key_skills(key_user)

        raise HTTPException(
            status_code=401,
            detail="Sign in or provide a valid Amosclaud Autonomous bearer key",
        )

    def authorize(self, request: Request, mode: str) -> AgentChainContext:
        normalized_mode = mode.strip().lower()
        required_skill = MODE_SKILLS.get(normalized_mode)
        if required_skill is None:
            choices = ", ".join(sorted(MODE_SKILLS))
            raise HTTPException(
                status_code=422,
                detail=f"Unsupported agent-chain mode. Choose one of: {choices}",
            )

        user, authentication, skills = self.authenticate(request)
        if required_skill not in skills:
            raise HTTPException(
                status_code=403,
                detail=(
                    f"This Autonomous key does not grant the '{required_skill}' "
                    f"skill required for mode '{normalized_mode}'"
                ),
            )

        return AgentChainContext(
            user=user,
            authentication=authentication,
            skills=skills,
            requested_mode=normalized_mode,
            required_skill=required_skill,
        )


agent_power_chain = AgentPowerChain()

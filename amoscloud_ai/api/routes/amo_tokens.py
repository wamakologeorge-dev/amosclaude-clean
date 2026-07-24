from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from amoscloud_ai.api.routes.core import _owner_user
from amoscloud_ai.core.tokens import AmosclaudTokenService, TokenError

router = APIRouter(prefix="/amo-tokens", tags=["amo-tokens"])


class TokenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    scopes: list[
        Literal[
            "workspace:read",
            "workspace:write",
            "agent:run",
            "router:read",
            "router:write",
            "core:admin",
        ]
    ] = Field(min_length=1, max_length=6)
    expires_in_days: int | None = Field(default=90, ge=1, le=3650)


def _service() -> AmosclaudTokenService:
    return AmosclaudTokenService(Path(os.getenv("AMOSCLAUD_CORE_DB", "/data/amosclaud-core.db")))


@router.get("")
def list_tokens(owner=Depends(_owner_user)) -> list[dict]:
    return _service().list_for_owner(int(owner["id"]))


@router.post("", status_code=201)
def issue_token(body: TokenCreate, owner=Depends(_owner_user)) -> dict:
    try:
        return _service().issue(
            name=body.name,
            owner_id=int(owner["id"]),
            scopes=list(body.scopes),
            expires_in_days=body.expires_in_days,
        )
    except TokenError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{token_id}")
def revoke_token(token_id: int, owner=Depends(_owner_user)) -> dict:
    if not _service().revoke(token_id, int(owner["id"])):
        raise HTTPException(status_code=404, detail="Token not found or already revoked")
    return {"id": token_id, "revoked": True}

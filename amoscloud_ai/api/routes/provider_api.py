"""Customer Amosclaud API keys, agent credits, and provider endpoint."""

from __future__ import annotations

import os
import uuid
from typing import Literal

import stripe
from fastapi import APIRouter, Cookie, Header, HTTPException
from pydantic import BaseModel, Field

from amoscloud_ai import provider
from amoscloud_ai.agent_tokens import (
    credit_tokens,
    debit_tokens,
    ensure_agent_schema,
    issue_api_key,
    key_hash,
    now,
)
from amoscloud_ai.api.routes.auth import _connect, get_user_from_session

router = APIRouter(prefix="/provider", tags=["amosclaud-provider"])

PACKS = {
    "starter": ("STRIPE_AGENT_STARTER_PRICE_ID", 1_000),
    "builder": ("STRIPE_AGENT_BUILDER_PRICE_ID", 5_000),
    "studio": ("STRIPE_AGENT_STUDIO_PRICE_ID", 15_000),
}


class KeyCreate(BaseModel):
    label: str = Field(default="My Amosclaud installation", min_length=2, max_length=100)


class TokenCheckout(BaseModel):
    pack: Literal["starter", "builder", "studio"]


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1, max_length=200_000)


class ChatCompletionRequest(BaseModel):
    model: str = Field(default="amosclaud-agent", max_length=100)
    messages: list[ChatMessage] = Field(min_length=1, max_length=100)


def _user(token: str | None):
    user = get_user_from_session(token)
    if not user:
        raise HTTPException(status_code=401, detail="Sign in to manage Amosclaud API access")
    return user


def _public_url() -> str:
    return os.getenv("AMOSCLAUD_PUBLIC_URL", "http://localhost:8000").strip().rstrip("/")


@router.get("/tokens")
def token_status(amos_session: str | None = Cookie(default=None)) -> dict:
    user = _user(amos_session)
    with _connect() as db:
        ensure_agent_schema(db)
        wallet = db.execute(
            "SELECT balance,updated_at FROM agent_token_wallets WHERE user_id=?", (user["id"],)
        ).fetchone()
        history = db.execute(
            """SELECT delta,reason,reference,created_at FROM agent_token_ledger
               WHERE user_id=? ORDER BY id DESC LIMIT 50""",
            (user["id"],),
        ).fetchall()
    return {
        "balance": int(wallet["balance"]) if wallet else 0,
        "updated_at": wallet["updated_at"] if wallet else None,
        "packs": [
            {"id": pack, "credits": credits, "available": bool(os.getenv(env_name))}
            for pack, (env_name, credits) in PACKS.items()
        ],
        "history": [dict(row) for row in history],
    }


@router.post("/tokens/checkout")
def token_checkout(
    body: TokenCheckout,
    amos_session: str | None = Cookie(default=None),
) -> dict[str, str]:
    user = _user(amos_session)
    secret = os.getenv("STRIPE_SECRET_KEY", "").strip()
    price_env, credits = PACKS[body.pack]
    price_id = os.getenv(price_env, "").strip()
    if not secret or not price_id:
        raise HTTPException(status_code=503, detail="This Amosclaud token pack is not configured")
    stripe.api_key = secret
    session = stripe.checkout.Session.create(
        mode="payment",
        line_items=[{"price": price_id, "quantity": 1}],
        customer_email=user["email"],
        client_reference_id=str(user["id"]),
        metadata={
            "kind": "agent_tokens",
            "amosclaud_user_id": str(user["id"]),
            "pack": body.pack,
            "credits": str(credits),
        },
        success_url=f"{_public_url()}/plans?tokens=success",
        cancel_url=f"{_public_url()}/plans?tokens=cancelled",
    )
    if not session.url:
        raise HTTPException(status_code=502, detail="Stripe did not return a checkout URL")
    return {"url": session.url}


@router.get("/keys")
def list_keys(amos_session: str | None = Cookie(default=None)) -> list[dict]:
    user = _user(amos_session)
    with _connect() as db:
        ensure_agent_schema(db)
        rows = db.execute(
            """SELECT id,key_prefix,label,created_at,last_used_at,revoked_at
               FROM agent_api_keys WHERE user_id=? ORDER BY id DESC""",
            (user["id"],),
        ).fetchall()
    return [dict(row) for row in rows]


@router.post("/keys", status_code=201)
def create_key(body: KeyCreate, amos_session: str | None = Cookie(default=None)) -> dict:
    user = _user(amos_session)
    with _connect() as db:
        key_id, raw, prefix = issue_api_key(db, int(user["id"]), body.label.strip())
    return {
        "id": key_id,
        "api_key": raw,
        "prefix": prefix,
        "warning": "Copy this key now. Amosclaud stores only its secure hash.",
    }


@router.delete("/keys/{key_id}", status_code=204)
def revoke_key(key_id: int, amos_session: str | None = Cookie(default=None)) -> None:
    user = _user(amos_session)
    with _connect() as db:
        ensure_agent_schema(db)
        cursor = db.execute(
            "UPDATE agent_api_keys SET revoked_at=? WHERE id=? AND user_id=? AND revoked_at IS NULL",
            (now(), key_id, user["id"]),
        )
        db.commit()
    if cursor.rowcount != 1:
        raise HTTPException(status_code=404, detail="Active API key not found")


def _authenticate(authorization: str | None):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="A valid Amosclaud API key is required")
    raw = authorization.removeprefix("Bearer ").strip()
    with _connect() as db:
        ensure_agent_schema(db)
        row = db.execute(
            """SELECT k.id,k.user_id,w.balance FROM agent_api_keys k
               LEFT JOIN agent_token_wallets w ON w.user_id=k.user_id
               WHERE k.key_hash=? AND k.revoked_at IS NULL""",
            (key_hash(raw),),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=401, detail="Amosclaud API key is invalid or revoked")
        db.execute("UPDATE agent_api_keys SET last_used_at=? WHERE id=?", (now(), row["id"]))
        db.commit()
        return dict(row)


@router.post("/chat/completions")
def chat_completions(
    body: ChatCompletionRequest,
    authorization: str | None = Header(default=None),
) -> dict:
    credential = _authenticate(authorization)
    cost = max(1, int(os.getenv("AMOSCLAUD_AGENT_CREDITS_PER_REQUEST", "1")))
    request_id = "agent-" + uuid.uuid4().hex
    with _connect() as db:
        if not debit_tokens(db, int(credential["user_id"]), cost, reference=request_id):
            raise HTTPException(
                status_code=402,
                detail={"code": "agent_tokens_required", "purchase_url": "/plans"},
            )

    messages = [message.model_dump() for message in body.messages]
    system = "\n".join(
        message["content"] for message in messages if message["role"] == "system"
    ) or "You are Amosclaud, a professional engineering agent."
    history = [message for message in messages if message["role"] != "system"]
    try:
        result = provider.reply(history, system)
        if result.status != "ready":
            raise RuntimeError("Owner model runtime is unavailable")
    except Exception:
        with _connect() as db:
            credit_tokens(
                db,
                int(credential["user_id"]),
                cost,
                reason="agent_request_refund",
                reference=request_id,
            )
        raise HTTPException(status_code=503, detail="Amosclaud agent runtime is unavailable")

    return {
        "id": request_id,
        "object": "chat.completion",
        "model": body.model,
        "provider": "amosclaud",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": result.reply}, "finish_reason": "stop"}],
        "usage": {"amosclaud_credits": cost},
    }

"""Customer Amosclaud API keys, agent credits, and provider endpoint."""

from __future__ import annotations

import os
import uuid
from typing import Any, Literal

import stripe
from fastapi import APIRouter, Cookie, Header, HTTPException
from pydantic import BaseModel, Field

from amoscloud_ai import provider
from amoscloud_ai.agent_credit_billing import (
    checkout_line_item,
    checkout_metadata,
    get_pack,
    public_packs,
    settle_paid_checkout,
    stripe_configured,
)
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


def _stripe_error(message: str, exc: Exception) -> HTTPException:
    request_id = getattr(exc, "request_id", None)
    detail = message if not request_id else f"{message} (Stripe request {request_id})"
    return HTTPException(status_code=502, detail=detail)


def _stripe_customer_id(user: Any) -> str:
    with _connect() as db:
        ensure_agent_schema(db)
        existing = db.execute(
            "SELECT stripe_customer_id FROM agent_billing_customers WHERE user_id=?",
            (user["id"],),
        ).fetchone()
        if existing and existing["stripe_customer_id"]:
            return str(existing["stripe_customer_id"])

    try:
        customer = stripe.Customer.create(
            email=user["email"],
            name=user["name"] if "name" in user.keys() else None,
            metadata={"amosclaud_user_id": str(user["id"]), "kind": "agent_credits"},
        )
    except stripe.error.StripeError as exc:
        raise _stripe_error("Stripe could not create the billing customer", exc) from exc

    customer_id = str(customer.id)
    with _connect() as db:
        ensure_agent_schema(db)
        db.execute(
            """INSERT INTO agent_billing_customers(user_id,stripe_customer_id,updated_at)
               VALUES (?,?,?)
               ON CONFLICT(user_id) DO UPDATE SET
                 stripe_customer_id=excluded.stripe_customer_id,
                 updated_at=excluded.updated_at""",
            (user["id"], customer_id, now()),
        )
        db.commit()
    return customer_id


def _session_owner(session: Any) -> int:
    metadata = getattr(session, "metadata", None) or {}
    if not isinstance(metadata, dict):
        metadata = dict(metadata)
    return int(
        metadata.get("amosclaud_user_id")
        or getattr(session, "client_reference_id", None)
        or 0
    )


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
    packs = public_packs()
    return {
        "balance": int(wallet["balance"]) if wallet else 0,
        "updated_at": wallet["updated_at"] if wallet else None,
        "checkout_available": any(pack["available"] for pack in packs),
        "checkout_provider": "stripe" if stripe_configured() else None,
        "payment_method_note": (
            "Stripe Checkout accepts cards and debit cards. Bank-account options appear when "
            "they are enabled and eligible in the Stripe Dashboard."
        ),
        "packs": packs,
        "history": [dict(row) for row in history],
    }


@router.post("/tokens/checkout")
def token_checkout(
    body: TokenCheckout,
    amos_session: str | None = Cookie(default=None),
) -> dict[str, str]:
    user = _user(amos_session)
    secret = os.getenv("STRIPE_SECRET_KEY", "").strip()
    pack = get_pack(body.pack)
    if not secret:
        raise HTTPException(
            status_code=503,
            detail="Stripe checkout is not configured. Add STRIPE_SECRET_KEY on the server.",
        )
    try:
        line_item = checkout_line_item(pack)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    stripe.api_key = secret
    customer_id = _stripe_customer_id(user)
    metadata = checkout_metadata(int(user["id"]), pack)
    try:
        session = stripe.checkout.Session.create(
            mode="payment",
            line_items=[line_item],
            customer=customer_id,
            client_reference_id=str(user["id"]),
            metadata=metadata,
            payment_intent_data={"metadata": metadata, "receipt_email": user["email"]},
            success_url=(
                f"{_public_url()}/api-access?checkout=success"
                "&session_id={CHECKOUT_SESSION_ID}"
            ),
            cancel_url=f"{_public_url()}/api-access?checkout=cancelled",
            submit_type="pay",
            locale="auto",
        )
    except stripe.error.StripeError as exc:
        raise _stripe_error("Stripe could not start checkout", exc) from exc

    if not session.url:
        raise HTTPException(status_code=502, detail="Stripe did not return a checkout URL")
    return {"url": str(session.url), "session_id": str(session.id)}


@router.get("/tokens/checkout/{session_id}")
def token_checkout_status(
    session_id: str,
    amos_session: str | None = Cookie(default=None),
) -> dict[str, object]:
    user = _user(amos_session)
    if not session_id.startswith("cs_") or len(session_id) > 255:
        raise HTTPException(status_code=400, detail="Stripe Checkout session is invalid")

    secret = os.getenv("STRIPE_SECRET_KEY", "").strip()
    if not secret:
        raise HTTPException(status_code=503, detail="Stripe checkout is not configured")
    stripe.api_key = secret
    try:
        session = stripe.checkout.Session.retrieve(session_id)
    except stripe.error.StripeError as exc:
        raise _stripe_error("Stripe could not confirm this checkout", exc) from exc

    if _session_owner(session) != int(user["id"]):
        raise HTTPException(status_code=404, detail="Checkout session was not found")

    try:
        with _connect() as db:
            credited, balance = settle_paid_checkout(
                db,
                session,
                expected_user_id=int(user["id"]),
            )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    payment_status = str(getattr(session, "payment_status", "unpaid"))
    status = str(getattr(session, "status", "open"))
    if payment_status == "paid":
        message = "Payment confirmed and agent credits are available."
    elif status == "complete":
        message = "Stripe accepted the payment details. Bank payments can take time to settle."
    else:
        message = "Checkout has not been completed."
    return {
        "session_id": session_id,
        "status": status,
        "payment_status": payment_status,
        "credited_now": credited,
        "balance": balance,
        "message": message,
    }


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
                detail={"code": "agent_tokens_required", "purchase_url": "/api-access"},
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
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": result.reply},
                "finish_reason": "stop",
            }
        ],
        "usage": {"amosclaud_credits": cost},
    }

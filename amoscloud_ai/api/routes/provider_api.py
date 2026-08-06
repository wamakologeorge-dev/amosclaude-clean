"""Customer Amosclaud API keys, paid activation, credits, and provider endpoint."""

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
    settle_paid_checkout,
)
from amoscloud_ai.agent_tokens import (
    api_access_is_activated,
    credit_tokens,
    debit_tokens,
    ensure_agent_schema,
    issue_api_key,
    key_hash,
    now,
)
from amoscloud_ai.api.routes.auth import _connect, get_user_from_session

router = APIRouter(prefix="/provider", tags=["amosclaud-provider"])

PAYMENT_LINKS = {
    "cash_app": "https://cash.app/$kenjamakulu",
    "bitcoin": "https://cash.app/launch/bitcoin/$kenjamakulu/pPi5bQWHLA",
}
PAYMENT_REASON = {
    "cash_app": "cash_app_payment",
    "bitcoin": "bitcoin_payment",
}
PACK_IDS = ("starter", "builder", "studio")


class KeyCreate(BaseModel):
    label: str = Field(
        default="My Amosclaud installation",
        min_length=2,
        max_length=100,
    )


class TokenCheckout(BaseModel):
    pack: Literal["starter", "builder", "studio"]


class PaymentActivation(BaseModel):
    user_email: str = Field(min_length=5, max_length=254)
    pack: Literal["starter", "builder", "studio"]
    method: Literal["cash_app", "bitcoin"]
    payment_reference: str = Field(min_length=4, max_length=200)


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1, max_length=200_000)


class ChatCompletionRequest(BaseModel):
    model: str = Field(default="amosclaud-agent", max_length=100)
    messages: list[ChatMessage] = Field(min_length=1, max_length=100)


def _user(token: str | None):
    user = get_user_from_session(token)
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Sign in to manage Amosclaud API access",
        )
    return user


def _admin(token: str | None):
    user = _user(token)
    if not bool(user["is_admin"]):
        raise HTTPException(status_code=403, detail="Administrator access required")
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

    user_keys = user.keys() if hasattr(user, "keys") else ()
    try:
        customer = stripe.Customer.create(
            email=user["email"],
            name=user["name"] if "name" in user_keys else None,
            metadata={
                "amosclaud_user_id": str(user["id"]),
                "kind": "agent_credits",
            },
        )
    except stripe.error.StripeError as exc:
        raise _stripe_error(
            "Stripe could not create the billing customer",
            exc,
        ) from exc

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
        try:
            metadata = dict(metadata)
        except (TypeError, ValueError):
            metadata = {}
    return int(
        metadata.get("amosclaud_user_id") or getattr(session, "client_reference_id", None) or 0
    )


def _wallet_balance(user_id: int) -> int:
    with _connect() as db:
        ensure_agent_schema(db)
        wallet = db.execute(
            "SELECT balance FROM agent_token_wallets WHERE user_id=?",
            (user_id,),
        ).fetchone()
    return int(wallet["balance"]) if wallet else 0


def _manual_packs() -> list[dict[str, object]]:
    return [
        {
            "id": pack.id,
            "name": pack.name,
            "credits": pack.credits,
            "available": True,
            "payment_methods": ["cash_app", "bitcoin"],
            "payment_note": (
                f'Include "Amosclaud {pack.name}" and the account email or GitHub '
                "username in the payment note."
            ),
        }
        for pack in (get_pack(pack_id) for pack_id in PACK_IDS)
    ]


def _payment_required() -> HTTPException:
    return HTTPException(
        status_code=402,
        detail=(
            "Pay with Cash App or Bitcoin and wait for Amosclaud to verify the "
            "payment before creating or using an Amosclaud API key."
        ),
    )


@router.get("/tokens")
def token_status(amos_session: str | None = Cookie(default=None)) -> dict:
    user = _user(amos_session)
    with _connect() as db:
        ensure_agent_schema(db)
        wallet = db.execute(
            "SELECT balance,updated_at FROM agent_token_wallets WHERE user_id=?",
            (user["id"],),
        ).fetchone()
        history = db.execute(
            """SELECT delta,reason,reference,created_at FROM agent_token_ledger
               WHERE user_id=? ORDER BY id DESC LIMIT 50""",
            (user["id"],),
        ).fetchall()
        activated = api_access_is_activated(
            db,
            int(user["id"]),
            is_admin=bool(user["is_admin"]),
        )
    return {
        "balance": int(wallet["balance"]) if wallet else 0,
        "updated_at": wallet["updated_at"] if wallet else None,
        "api_activated": activated,
        "payment_required": not activated,
        "checkout_available": True,
        "checkout_provider": "cash_app_or_bitcoin_manual_verification",
        "payment_methods": [{"id": method, "url": url} for method, url in PAYMENT_LINKS.items()],
        "payment_method_note": (
            "Cash App and Bitcoin are the only enabled payment methods. Amosclaud "
            "activates API access only after an administrator verifies the payment."
        ),
        "packs": _manual_packs(),
        "history": [dict(row) for row in history],
    }


@router.post("/tokens/checkout")
def token_checkout(
    body: TokenCheckout,
    amos_session: str | None = Cookie(default=None),
) -> dict[str, str]:
    _user(amos_session)
    get_pack(body.pack)
    raise HTTPException(
        status_code=410,
        detail=(
            "Stripe checkout is disabled. Pay with Cash App or Bitcoin from "
            "/api-access and wait for manual verification."
        ),
    )


@router.get("/tokens/checkout/{session_id}")
def token_checkout_status(
    session_id: str,
    amos_session: str | None = Cookie(default=None),
) -> dict[str, object]:
    _user(amos_session)
    raise HTTPException(
        status_code=410,
        detail=(
            "Stripe checkout is disabled. Cash App and Bitcoin payments are "
            "activated only after manual verification."
        ),
    )


@router.post("/payments/activate")
def activate_paid_api_access(
    body: PaymentActivation,
    amos_session: str | None = Cookie(default=None),
) -> dict[str, object]:
    """Credit and activate one externally verified Cash App or Bitcoin payment."""

    reviewer = _admin(amos_session)
    email = body.user_email.strip().lower()
    payment_reference = body.payment_reference.strip()
    pack = get_pack(body.pack)
    with _connect() as db:
        ensure_agent_schema(db)
        account = db.execute(
            "SELECT id,email FROM users WHERE email=? COLLATE NOCASE",
            (email,),
        ).fetchone()
        if not account:
            raise HTTPException(status_code=404, detail="Amosclaud account not found")
        reason = PAYMENT_REASON[body.method]
        credited = credit_tokens(
            db,
            int(account["id"]),
            pack.credits,
            reason=reason,
            reference=payment_reference,
        )
        if not credited:
            raise HTTPException(
                status_code=409,
                detail="This payment reference was already verified",
            )
        wallet = db.execute(
            "SELECT balance FROM agent_token_wallets WHERE user_id=?",
            (account["id"],),
        ).fetchone()
    return {
        "activated": True,
        "user_id": int(account["id"]),
        "user_email": account["email"],
        "pack": pack.id,
        "credits_added": pack.credits,
        "balance": int(wallet["balance"]) if wallet else pack.credits,
        "payment_method": body.method,
        "payment_reference": payment_reference,
        "verified_by": int(reviewer["id"]),
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
def create_key(
    body: KeyCreate,
    amos_session: str | None = Cookie(default=None),
) -> dict:
    user = _user(amos_session)
    with _connect() as db:
        if not api_access_is_activated(
            db,
            int(user["id"]),
            is_admin=bool(user["is_admin"]),
        ):
            raise _payment_required()
        key_id, raw, prefix = issue_api_key(
            db,
            int(user["id"]),
            body.label.strip(),
        )
    return {
        "id": key_id,
        "api_key": raw,
        "prefix": prefix,
        "activated": True,
        "warning": "Copy this key now. Amosclaud stores only its secure hash.",
    }


@router.delete("/keys/{key_id}", status_code=204)
def revoke_key(
    key_id: int,
    amos_session: str | None = Cookie(default=None),
) -> None:
    user = _user(amos_session)
    with _connect() as db:
        ensure_agent_schema(db)
        cursor = db.execute(
            """UPDATE agent_api_keys SET revoked_at=?
               WHERE id=? AND user_id=? AND revoked_at IS NULL""",
            (now(), key_id, user["id"]),
        )
        db.commit()
    if cursor.rowcount != 1:
        raise HTTPException(status_code=404, detail="Active API key not found")


def _authenticate(authorization: str | None):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="A valid Amosclaud API key is required",
        )
    raw = authorization.removeprefix("Bearer ").strip()
    with _connect() as db:
        ensure_agent_schema(db)
        row = db.execute(
            """SELECT k.id,k.user_id,w.balance,u.is_admin
               FROM agent_api_keys k
               JOIN users u ON u.id=k.user_id
               LEFT JOIN agent_token_wallets w ON w.user_id=k.user_id
               WHERE k.key_hash=? AND k.revoked_at IS NULL""",
            (key_hash(raw),),
        ).fetchone()
        if not row:
            raise HTTPException(
                status_code=401,
                detail="Amosclaud API key is invalid or revoked",
            )
        if not api_access_is_activated(
            db,
            int(row["user_id"]),
            is_admin=bool(row["is_admin"]),
        ):
            raise _payment_required()
        db.execute(
            "UPDATE agent_api_keys SET last_used_at=? WHERE id=?",
            (now(), row["id"]),
        )
        db.commit()
        return dict(row)


@router.post("/chat/completions")
def chat_completions(
    body: ChatCompletionRequest,
    authorization: str | None = Header(default=None),
) -> dict:
    credential = _authenticate(authorization)
    cost = max(
        1,
        int(os.getenv("AMOSCLAUD_AGENT_CREDITS_PER_REQUEST", "1")),
    )
    request_id = "agent-" + uuid.uuid4().hex
    with _connect() as db:
        if not debit_tokens(
            db,
            int(credential["user_id"]),
            cost,
            reference=request_id,
        ):
            raise HTTPException(
                status_code=402,
                detail={
                    "code": "agent_tokens_required",
                    "purchase_url": "/api-access",
                },
            )

    messages = [message.model_dump() for message in body.messages]
    system = (
        "\n".join(message["content"] for message in messages if message["role"] == "system")
        or "You are Amosclaud, a professional engineering agent."
    )
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
        raise HTTPException(
            status_code=503,
            detail="Amosclaud agent runtime is unavailable",
        )

    return {
        "id": request_id,
        "object": "chat.completion",
        "model": body.model,
        "provider": "amosclaud",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": result.reply,
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"amosclaud_credits": cost},
    }


__all__ = [
    "PAYMENT_LINKS",
    "PaymentActivation",
    "activate_paid_api_access",
    "checkout_line_item",
    "checkout_metadata",
    "settle_paid_checkout",
]

"""Stripe configuration and idempotent settlement for prepaid agent credits."""

from __future__ import annotations

import os
import re
import sqlite3
from dataclasses import dataclass
from typing import Any

from amoscloud_ai.agent_tokens import credit_tokens, ensure_agent_schema

_CURRENCY = re.compile(r"^[a-z]{3}$")


@dataclass(frozen=True)
class AgentCreditPack:
    id: str
    name: str
    credits: int
    price_id_env: str
    amount_cents_env: str

    @property
    def price_id(self) -> str:
        return os.getenv(self.price_id_env, "").strip()

    @property
    def amount_cents(self) -> int | None:
        raw = os.getenv(self.amount_cents_env, "").strip()
        if not raw:
            return None
        try:
            amount = int(raw)
        except ValueError:
            return None
        return amount if amount > 0 else None

    @property
    def configured(self) -> bool:
        return bool(self.price_id or self.amount_cents)


PACKS = {
    "starter": AgentCreditPack(
        id="starter",
        name="Starter",
        credits=1_000,
        price_id_env="STRIPE_AGENT_STARTER_PRICE_ID",
        amount_cents_env="STRIPE_AGENT_STARTER_AMOUNT_CENTS",
    ),
    "builder": AgentCreditPack(
        id="builder",
        name="Builder",
        credits=5_000,
        price_id_env="STRIPE_AGENT_BUILDER_PRICE_ID",
        amount_cents_env="STRIPE_AGENT_BUILDER_AMOUNT_CENTS",
    ),
    "studio": AgentCreditPack(
        id="studio",
        name="Studio",
        credits=15_000,
        price_id_env="STRIPE_AGENT_STUDIO_PRICE_ID",
        amount_cents_env="STRIPE_AGENT_STUDIO_AMOUNT_CENTS",
    ),
}


def currency() -> str:
    value = os.getenv("STRIPE_AGENT_CURRENCY", "usd").strip().lower()
    return value if _CURRENCY.fullmatch(value) else "usd"


def stripe_secret_configured() -> bool:
    return bool(os.getenv("STRIPE_SECRET_KEY", "").strip())


def stripe_webhook_configured() -> bool:
    return bool(os.getenv("STRIPE_WEBHOOK_SECRET", "").strip())


def stripe_configured() -> bool:
    return stripe_secret_configured() and stripe_webhook_configured()


def get_pack(pack_id: str) -> AgentCreditPack:
    try:
        return PACKS[pack_id]
    except KeyError as exc:
        raise ValueError("Unknown agent credit pack") from exc


def checkout_line_item(pack: AgentCreditPack) -> dict[str, Any]:
    if pack.price_id:
        return {"price": pack.price_id, "quantity": 1}
    if pack.amount_cents:
        return {
            "price_data": {
                "currency": currency(),
                "unit_amount": pack.amount_cents,
                "product_data": {
                    "name": f"Amosclaud Agent Credits — {pack.name}",
                    "description": f"{pack.credits:,} prepaid Amosclaud agent credits",
                    "metadata": {"pack": pack.id, "credits": str(pack.credits)},
                },
            },
            "quantity": 1,
        }
    raise ValueError(f"Configure {pack.price_id_env} or {pack.amount_cents_env} before checkout")


def public_pack(pack: AgentCreditPack) -> dict[str, Any]:
    missing: list[str] = []
    if not stripe_secret_configured():
        missing.append("STRIPE_SECRET_KEY")
    if not stripe_webhook_configured():
        missing.append("STRIPE_WEBHOOK_SECRET")
    if not pack.configured:
        missing.append(f"{pack.price_id_env} or {pack.amount_cents_env}")
    return {
        "id": pack.id,
        "name": pack.name,
        "credits": pack.credits,
        "available": not missing,
        "currency": currency(),
        "unit_amount": pack.amount_cents,
        "price_source": "stripe_price" if pack.price_id else "inline_amount",
        "configuration_message": (
            "Ready for secure Stripe Checkout"
            if not missing
            else "Checkout setup incomplete: " + ", ".join(missing)
        ),
    }


def public_packs() -> list[dict[str, Any]]:
    return [public_pack(pack) for pack in PACKS.values()]


def checkout_metadata(user_id: int, pack: AgentCreditPack) -> dict[str, str]:
    return {
        "kind": "agent_tokens",
        "amosclaud_user_id": str(user_id),
        "pack": pack.id,
        "credits": str(pack.credits),
    }


def _value(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _metadata(checkout_session: Any) -> dict[str, Any]:
    raw = _value(checkout_session, "metadata", {}) or {}
    if isinstance(raw, dict):
        return raw
    try:
        return dict(raw)
    except (TypeError, ValueError):
        return {}


def settle_paid_checkout(
    db: sqlite3.Connection,
    checkout_session: Any,
    *,
    expected_user_id: int | None = None,
) -> tuple[bool, int]:
    """Credit one paid Checkout Session exactly once and return wallet balance."""

    metadata = _metadata(checkout_session)
    if metadata.get("kind") != "agent_tokens":
        return False, 0
    if _value(checkout_session, "payment_status") != "paid":
        return False, 0

    pack = get_pack(str(metadata.get("pack") or ""))
    user_id = int(
        metadata.get("amosclaud_user_id") or _value(checkout_session, "client_reference_id") or 0
    )
    if not user_id or (expected_user_id is not None and user_id != expected_user_id):
        raise ValueError("Stripe Checkout session does not belong to this Amosclaud account")

    session_id = str(_value(checkout_session, "id") or "").strip()
    if not session_id.startswith("cs_"):
        raise ValueError("Stripe Checkout session identifier is invalid")

    if not pack.price_id and pack.amount_cents:
        amount_total = _value(checkout_session, "amount_total")
        session_currency = str(_value(checkout_session, "currency") or "").lower()
        if amount_total is not None and int(amount_total) != pack.amount_cents:
            raise ValueError("Stripe Checkout amount does not match the configured pack")
        if session_currency and session_currency != currency():
            raise ValueError("Stripe Checkout currency does not match the configured pack")

    ensure_agent_schema(db)
    credited = credit_tokens(
        db,
        user_id,
        pack.credits,
        reason="stripe_token_purchase",
        reference=f"stripe_checkout:{session_id}",
    )
    wallet = db.execute(
        "SELECT balance FROM agent_token_wallets WHERE user_id=?", (user_id,)
    ).fetchone()
    balance = int(wallet["balance"] if hasattr(wallet, "keys") else wallet[0]) if wallet else 0
    return credited, balance

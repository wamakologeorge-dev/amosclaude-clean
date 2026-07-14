"""Commercial plans, Stripe subscriptions, and manual license activation."""

from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
from datetime import datetime, timezone
from typing import Literal

import stripe
from fastapi import APIRouter, Cookie, Header, HTTPException, Request
from pydantic import BaseModel, Field

from amoscloud_ai.api.routes.auth import _connect, get_user_from_session
from amoscloud_ai.agent_tokens import credit_tokens

router = APIRouter(prefix="/billing", tags=["billing"])

ACTIVE_STATUSES = {"active", "trialing"}
PLAN_FEATURES = {
    "community": [
        "Self-hosted folder server",
        "Local repositories and storage",
        "Community updates",
        "Bring your own model runtime",
    ],
    "full": [
        "All Community features",
        "Full autonomous agent workflows",
        "Advanced build, test, review, and deployment tools",
        "External provider API-key adapters",
        "Priority package updates",
        "Commercial-use entitlement",
    ],
}


class CheckoutRequest(BaseModel):
    interval: Literal["monthly", "annual"]


class LicenseActivationRequest(BaseModel):
    key: str = Field(..., min_length=20, max_length=200)


class LicenseIssueRequest(BaseModel):
    label: str = Field(..., min_length=2, max_length=120)
    expires_at: datetime | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _license_hash(value: str) -> str:
    return hashlib.sha256(value.strip().upper().encode()).hexdigest()


def _require_user(token: str | None) -> sqlite3.Row:
    user = get_user_from_session(token)
    if not user:
        raise HTTPException(status_code=401, detail="Sign in to manage an Amosclaud plan")
    return user


def _ensure_schema(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS billing_subscriptions (
            user_id INTEGER PRIMARY KEY,
            plan TEXT NOT NULL DEFAULT 'community',
            status TEXT NOT NULL DEFAULT 'inactive',
            billing_interval TEXT,
            stripe_customer_id TEXT UNIQUE,
            stripe_subscription_id TEXT UNIQUE,
            current_period_end TEXT,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS billing_license_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key_hash TEXT NOT NULL UNIQUE,
            label TEXT NOT NULL,
            plan TEXT NOT NULL DEFAULT 'full',
            issued_by_user_id INTEGER NOT NULL,
            activated_by_user_id INTEGER,
            issued_at TEXT NOT NULL,
            activated_at TEXT,
            expires_at TEXT,
            revoked_at TEXT,
            FOREIGN KEY(issued_by_user_id) REFERENCES users(id),
            FOREIGN KEY(activated_by_user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS billing_webhook_events (
            event_id TEXT PRIMARY KEY,
            event_type TEXT NOT NULL,
            processed_at TEXT NOT NULL
        );
        """
    )
    db.commit()


def _stripe_ready() -> bool:
    return bool(
        os.getenv("STRIPE_SECRET_KEY")
        and os.getenv("STRIPE_WEBHOOK_SECRET")
        and os.getenv("STRIPE_FULL_MONTHLY_PRICE_ID")
        and os.getenv("STRIPE_FULL_ANNUAL_PRICE_ID")
    )


def _price_id(interval: str) -> str:
    name = "STRIPE_FULL_MONTHLY_PRICE_ID" if interval == "monthly" else "STRIPE_FULL_ANNUAL_PRICE_ID"
    value = os.getenv(name, "").strip()
    if not value:
        raise HTTPException(status_code=503, detail=f"{name} is not configured")
    return value


def _base_url() -> str:
    return os.getenv("AMOSCLAUD_PUBLIC_URL", "http://localhost:8000").strip().rstrip("/")


def _entitlement(db: sqlite3.Connection, user_id: int) -> dict[str, object]:
    _ensure_schema(db)
    subscription = db.execute(
        "SELECT * FROM billing_subscriptions WHERE user_id=?", (user_id,)
    ).fetchone()
    if subscription and subscription["plan"] == "full" and subscription["status"] in ACTIVE_STATUSES:
        return {
            "plan": "full",
            "active": True,
            "source": "stripe",
            "status": subscription["status"],
            "billing_interval": subscription["billing_interval"],
            "renews_at": subscription["current_period_end"],
            "features": PLAN_FEATURES["full"],
        }

    now = _now()
    license_row = db.execute(
        """SELECT * FROM billing_license_keys
           WHERE activated_by_user_id=? AND revoked_at IS NULL
             AND (expires_at IS NULL OR expires_at>?)
           ORDER BY activated_at DESC LIMIT 1""",
        (user_id, now),
    ).fetchone()
    if license_row:
        return {
            "plan": "full",
            "active": True,
            "source": "license",
            "status": "active",
            "billing_interval": None,
            "renews_at": license_row["expires_at"],
            "features": PLAN_FEATURES["full"],
        }

    return {
        "plan": "community",
        "active": True,
        "source": "included",
        "status": "active",
        "billing_interval": None,
        "renews_at": None,
        "features": PLAN_FEATURES["community"],
    }


def has_full_package(user_id: int) -> bool:
    with _connect() as db:
        return _entitlement(db, user_id)["plan"] == "full"


def require_full_package(user_id: int) -> None:
    if not has_full_package(user_id):
        raise HTTPException(
            status_code=402,
            detail={"code": "full_package_required", "upgrade_url": "/plans"},
        )


@router.get("/plans")
def plans() -> dict[str, object]:
    return {
        "plans": [
            {
                "id": "community",
                "name": "Amosclaud Community",
                "description": "The self-hosted foundation for personal projects.",
                "features": PLAN_FEATURES["community"],
                "included": True,
            },
            {
                "id": "full",
                "name": "Amosclaud Full Package",
                "description": "The complete self-hosted agent provider, build platform, and server.",
                "features": PLAN_FEATURES["full"],
                "monthly_price_id_configured": bool(os.getenv("STRIPE_FULL_MONTHLY_PRICE_ID")),
                "annual_price_id_configured": bool(os.getenv("STRIPE_FULL_ANNUAL_PRICE_ID")),
            },
        ],
        "checkout_available": _stripe_ready(),
    }


@router.get("/status")
def billing_status(amos_session: str | None = Cookie(default=None)) -> dict[str, object]:
    user = _require_user(amos_session)
    with _connect() as db:
        return _entitlement(db, int(user["id"]))


@router.post("/checkout")
def create_checkout(
    body: CheckoutRequest,
    amos_session: str | None = Cookie(default=None),
) -> dict[str, str]:
    user = _require_user(amos_session)
    secret = os.getenv("STRIPE_SECRET_KEY", "").strip()
    if not secret:
        raise HTTPException(status_code=503, detail="Stripe checkout is not configured")
    stripe.api_key = secret

    with _connect() as db:
        _ensure_schema(db)
        existing = db.execute(
            "SELECT stripe_customer_id FROM billing_subscriptions WHERE user_id=?",
            (user["id"],),
        ).fetchone()

    parameters: dict[str, object] = {
        "mode": "subscription",
        "line_items": [{"price": _price_id(body.interval), "quantity": 1}],
        "success_url": f"{_base_url()}/plans?checkout=success",
        "cancel_url": f"{_base_url()}/plans?checkout=cancelled",
        "client_reference_id": str(user["id"]),
        "metadata": {"amosclaud_user_id": str(user["id"]), "plan": "full", "interval": body.interval},
        "subscription_data": {
            "metadata": {"amosclaud_user_id": str(user["id"]), "plan": "full", "interval": body.interval}
        },
        "allow_promotion_codes": True,
    }
    if existing and existing["stripe_customer_id"]:
        parameters["customer"] = existing["stripe_customer_id"]
    else:
        parameters["customer_email"] = user["email"]

    session = stripe.checkout.Session.create(**parameters)
    if not session.url:
        raise HTTPException(status_code=502, detail="Stripe did not return a checkout URL")
    return {"url": session.url}


@router.post("/portal")
def customer_portal(amos_session: str | None = Cookie(default=None)) -> dict[str, str]:
    user = _require_user(amos_session)
    secret = os.getenv("STRIPE_SECRET_KEY", "").strip()
    if not secret:
        raise HTTPException(status_code=503, detail="Stripe billing is not configured")
    stripe.api_key = secret
    with _connect() as db:
        _ensure_schema(db)
        row = db.execute(
            "SELECT stripe_customer_id FROM billing_subscriptions WHERE user_id=?",
            (user["id"],),
        ).fetchone()
    if not row or not row["stripe_customer_id"]:
        raise HTTPException(status_code=404, detail="No Stripe customer exists for this account")
    session = stripe.billing_portal.Session.create(
        customer=row["stripe_customer_id"],
        return_url=f"{_base_url()}/plans",
    )
    return {"url": session.url}


@router.post("/license/activate")
def activate_license(
    body: LicenseActivationRequest,
    amos_session: str | None = Cookie(default=None),
) -> dict[str, object]:
    user = _require_user(amos_session)
    key_hash = _license_hash(body.key)
    with _connect() as db:
        _ensure_schema(db)
        row = db.execute(
            "SELECT * FROM billing_license_keys WHERE key_hash=?", (key_hash,)
        ).fetchone()
        if not row or row["revoked_at"]:
            raise HTTPException(status_code=400, detail="The license key is invalid or revoked")
        if row["expires_at"] and row["expires_at"] <= _now():
            raise HTTPException(status_code=400, detail="The license key has expired")
        if row["activated_by_user_id"] and row["activated_by_user_id"] != user["id"]:
            raise HTTPException(status_code=409, detail="The license key is already activated")
        db.execute(
            """UPDATE billing_license_keys
               SET activated_by_user_id=?,activated_at=COALESCE(activated_at,?)
               WHERE id=?""",
            (user["id"], _now(), row["id"]),
        )
        db.commit()
        return _entitlement(db, int(user["id"]))


@router.post("/licenses", status_code=201)
def issue_license(
    body: LicenseIssueRequest,
    amos_session: str | None = Cookie(default=None),
) -> dict[str, object]:
    admin = _require_user(amos_session)
    if not bool(admin["is_admin"]):
        raise HTTPException(status_code=403, detail="Administrator access is required")
    raw_key = "AMOS-FULL-" + secrets.token_urlsafe(24).upper().replace("_", "-")
    with _connect() as db:
        _ensure_schema(db)
        cursor = db.execute(
            """INSERT INTO billing_license_keys
               (key_hash,label,plan,issued_by_user_id,issued_at,expires_at)
               VALUES (?,?,'full',?,?,?)""",
            (
                _license_hash(raw_key),
                body.label.strip(),
                admin["id"],
                _now(),
                body.expires_at.astimezone(timezone.utc).isoformat() if body.expires_at else None,
            ),
        )
        db.commit()
    return {
        "id": cursor.lastrowid,
        "key": raw_key,
        "label": body.label.strip(),
        "expires_at": body.expires_at,
        "warning": "This key is shown once. Store it securely.",
    }


def _record_subscription(db: sqlite3.Connection, subscription: dict, user_id: int | None = None) -> None:
    metadata = subscription.get("metadata") or {}
    resolved_user_id = user_id or int(metadata.get("amosclaud_user_id") or 0)
    customer_id = subscription.get("customer")
    if not resolved_user_id and customer_id:
        row = db.execute(
            "SELECT user_id FROM billing_subscriptions WHERE stripe_customer_id=?",
            (customer_id,),
        ).fetchone()
        resolved_user_id = int(row["user_id"]) if row else 0
    if not resolved_user_id:
        return
    period_end = subscription.get("current_period_end")
    period_iso = (
        datetime.fromtimestamp(period_end, timezone.utc).isoformat() if period_end else None
    )
    db.execute(
        """INSERT INTO billing_subscriptions
           (user_id,plan,status,billing_interval,stripe_customer_id,stripe_subscription_id,current_period_end,updated_at)
           VALUES (?,'full',?,?,?,?,?,?)
           ON CONFLICT(user_id) DO UPDATE SET
             plan='full',status=excluded.status,billing_interval=excluded.billing_interval,
             stripe_customer_id=excluded.stripe_customer_id,
             stripe_subscription_id=excluded.stripe_subscription_id,
             current_period_end=excluded.current_period_end,updated_at=excluded.updated_at""",
        (
            resolved_user_id,
            subscription.get("status", "inactive"),
            metadata.get("interval"),
            customer_id,
            subscription.get("id"),
            period_iso,
            _now(),
        ),
    )


@router.post("/webhook", include_in_schema=False)
async def stripe_webhook(
    request: Request,
    stripe_signature: str | None = Header(default=None, alias="Stripe-Signature"),
) -> dict[str, bool]:
    secret = os.getenv("STRIPE_WEBHOOK_SECRET", "").strip()
    if not secret or not stripe_signature:
        raise HTTPException(status_code=400, detail="Stripe webhook verification is not configured")
    try:
        event = stripe.Webhook.construct_event(await request.body(), stripe_signature, secret)
    except (ValueError, stripe.error.SignatureVerificationError) as exc:
        raise HTTPException(status_code=400, detail="Invalid Stripe webhook") from exc

    event_id = event["id"]
    event_type = event["type"]
    obj = event["data"]["object"]
    with _connect() as db:
        _ensure_schema(db)
        if db.execute(
            "SELECT 1 FROM billing_webhook_events WHERE event_id=?", (event_id,)
        ).fetchone():
            return {"received": True}

        metadata = obj.get("metadata") or {}
        if (
            event_type == "checkout.session.completed"
            and metadata.get("kind") == "agent_tokens"
            and obj.get("payment_status") == "paid"
        ):
            user_id = int(metadata.get("amosclaud_user_id") or obj.get("client_reference_id") or 0)
            credits = int(metadata.get("credits") or 0)
            if user_id and credits:
                credit_tokens(
                    db,
                    user_id,
                    credits,
                    reason="stripe_token_purchase",
                    reference=event_id,
                )
        elif event_type == "checkout.session.completed" and obj.get("subscription"):
            stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
            subscription = stripe.Subscription.retrieve(obj["subscription"])
            user_id = int((obj.get("metadata") or {}).get("amosclaud_user_id") or obj.get("client_reference_id") or 0)
            _record_subscription(db, dict(subscription), user_id)
        elif event_type in {
            "customer.subscription.created",
            "customer.subscription.updated",
            "customer.subscription.deleted",
        }:
            _record_subscription(db, dict(obj))

        db.execute(
            "INSERT INTO billing_webhook_events(event_id,event_type,processed_at) VALUES (?,?,?)",
            (event_id, event_type, _now()),
        )
        db.commit()
    return {"received": True}

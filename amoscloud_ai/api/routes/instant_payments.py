"""Verified Cash App Pay and Bitcoin payments for timed Full Package access."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Cookie, Header, HTTPException, Request
from pydantic import BaseModel, Field

from amoscloud_ai.api.routes.auth import _connect, get_user_from_session
from amoscloud_ai.payment_entitlements import (
    active_time_entitlement,
    amount_display,
    create_payment_order,
    ensure_payment_schema,
    get_payment_order,
    get_provider_order,
    grant_payment_entitlement,
    instant_access_days,
    instant_price_cents,
    record_webhook_event,
    revoke_payment_entitlement,
    update_payment_order,
)

router = APIRouter(prefix="/billing", tags=["billing"])
SQUARE_API_VERSION_DEFAULT = "2026-05-20"


class CashAppPaymentRequest(BaseModel):
    order_id: str = Field(..., min_length=12, max_length=120)
    source_id: str = Field(..., min_length=8, max_length=500)


def _require_user(token: str | None) -> sqlite3.Row:
    user = get_user_from_session(token)
    if not user:
        raise HTTPException(status_code=401, detail="Sign in before starting a payment")
    return user


def _public_base_url() -> str:
    return os.getenv("AMOSCLAUD_PUBLIC_URL", "http://localhost:8000").strip().rstrip("/")


def _square_environment() -> str:
    value = os.getenv("SQUARE_ENVIRONMENT", "production").strip().lower()
    if value not in {"production", "sandbox"}:
        raise RuntimeError("SQUARE_ENVIRONMENT must be production or sandbox")
    return value


def _square_api_base() -> str:
    return (
        "https://connect.squareupsandbox.com"
        if _square_environment() == "sandbox"
        else "https://connect.squareup.com"
    )


def _square_script_url() -> str:
    return (
        "https://sandbox.web.squarecdn.com/v1/square.js"
        if _square_environment() == "sandbox"
        else "https://web.squarecdn.com/v1/square.js"
    )


def _square_settings() -> dict[str, str]:
    return {
        "application_id": os.getenv("SQUARE_APPLICATION_ID", "").strip(),
        "location_id": os.getenv("SQUARE_LOCATION_ID", "").strip(),
        "access_token": os.getenv("SQUARE_ACCESS_TOKEN", "").strip(),
        "webhook_signature_key": os.getenv("SQUARE_WEBHOOK_SIGNATURE_KEY", "").strip(),
        "webhook_notification_url": os.getenv(
            "SQUARE_WEBHOOK_NOTIFICATION_URL",
            f"{_public_base_url()}/api/v1/billing/webhooks/square",
        ).strip(),
        "merchant_id": os.getenv("SQUARE_MERCHANT_ID", "").strip(),
        "api_version": os.getenv(
            "SQUARE_API_VERSION",
            SQUARE_API_VERSION_DEFAULT,
        ).strip(),
    }


def _square_ready() -> bool:
    settings = _square_settings()
    return all(
        settings[name]
        for name in (
            "application_id",
            "location_id",
            "access_token",
            "webhook_signature_key",
            "webhook_notification_url",
        )
    )


def _btcpay_settings() -> dict[str, str]:
    return {
        "server_url": os.getenv("BTCPAY_SERVER_URL", "").strip().rstrip("/"),
        "store_id": os.getenv("BTCPAY_STORE_ID", "").strip(),
        "api_key": os.getenv("BTCPAY_API_KEY", "").strip(),
        "webhook_secret": os.getenv("BTCPAY_WEBHOOK_SECRET", "").strip(),
    }


def _btcpay_ready() -> bool:
    settings = _btcpay_settings()
    return all(settings.values())


def _order_is_expired(order: sqlite3.Row) -> bool:
    expires_at = datetime.fromisoformat(order["expires_at"])
    if not expires_at.tzinfo:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at <= datetime.now(timezone.utc)


def _order_payload(db: sqlite3.Connection, order: sqlite3.Row) -> dict[str, object]:
    entitlement = active_time_entitlement(db, int(order["user_id"]))
    return {
        "order_id": order["public_id"],
        "provider": order["provider"],
        "status": order["status"],
        "amount_cents": order["amount_cents"],
        "amount": f"{int(order['amount_cents']) / 100:.2f}",
        "currency": order["currency"],
        "expires_at": order["expires_at"],
        "access_active": bool(entitlement),
        "access_expires_at": entitlement["expires_at"] if entitlement else None,
        "remaining_seconds": entitlement["remaining_seconds"] if entitlement else 0,
        "redirect_url": "/cloud/agent?payment=activated" if entitlement else None,
    }


def _validate_order_for_payment(
    order: sqlite3.Row | None,
    *,
    provider: str,
) -> sqlite3.Row:
    if not order or order["provider"] != provider:
        raise HTTPException(status_code=404, detail="Payment order not found")
    if order["status"] == "completed":
        return order
    if order["status"] not in {"pending", "processing"}:
        raise HTTPException(status_code=409, detail="This payment order cannot be used")
    if _order_is_expired(order):
        raise HTTPException(status_code=410, detail="This payment order expired")
    return order


def _verify_square_signature(raw_body: bytes, supplied_signature: str | None) -> bool:
    settings = _square_settings()
    if not supplied_signature or not settings["webhook_signature_key"]:
        return False
    payload = settings["webhook_notification_url"].encode("utf-8") + raw_body
    digest = hmac.new(
        settings["webhook_signature_key"].encode("utf-8"),
        payload,
        hashlib.sha256,
    ).digest()
    expected = base64.b64encode(digest).decode("ascii")
    return hmac.compare_digest(expected, supplied_signature)


def _verify_btcpay_signature(raw_body: bytes, supplied_signature: str | None) -> bool:
    secret = _btcpay_settings()["webhook_secret"]
    if not secret or not supplied_signature:
        return False
    expected = "sha256=" + hmac.new(
        secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, supplied_signature)


def _event_seen(db: sqlite3.Connection, provider: str, event_id: str) -> bool:
    ensure_payment_schema(db)
    return bool(
        db.execute(
            """
            SELECT 1 FROM billing_instant_webhook_events
            WHERE provider=? AND event_id=?
            """,
            (provider, event_id),
        ).fetchone()
    )


def _mark_event(
    db: sqlite3.Connection,
    *,
    provider: str,
    event_id: str,
    event_type: str,
) -> None:
    record_webhook_event(
        db,
        provider=provider,
        event_id=event_id,
        event_type=event_type,
    )


def _square_payment_order(
    db: sqlite3.Connection,
    payment: dict[str, Any],
) -> sqlite3.Row | None:
    return get_provider_order(
        db,
        provider="cash_app",
        provider_payment_id=str(payment.get("id") or "") or None,
        public_id=str(payment.get("reference_id") or "") or None,
    )


def _validate_square_payment(
    order: sqlite3.Row,
    payment: dict[str, Any],
) -> None:
    settings = _square_settings()
    money = payment.get("amount_money") or {}
    if int(money.get("amount") or 0) != int(order["amount_cents"]):
        raise ValueError("Square payment amount does not match the Amosclaud order")
    if str(money.get("currency") or "").upper() != str(order["currency"]).upper():
        raise ValueError("Square payment currency does not match the Amosclaud order")
    if settings["location_id"] and payment.get("location_id") != settings["location_id"]:
        raise ValueError("Square payment location does not match Amosclaud")


@router.get("/instant/config")
def instant_payment_config() -> dict[str, object]:
    square = _square_settings()
    square_enabled = _square_ready()
    return {
        "price_cents": instant_price_cents(),
        "amount": amount_display(),
        "currency": "USD",
        "access_days": instant_access_days(),
        "cash_app": {
            "enabled": square_enabled,
            "application_id": square["application_id"] if square_enabled else None,
            "location_id": square["location_id"] if square_enabled else None,
            "script_url": _square_script_url() if square_enabled else None,
            "environment": _square_environment(),
        },
        "bitcoin": {"enabled": _btcpay_ready()},
    }


@router.post("/instant/cash-app/start")
def start_cash_app_payment(
    amos_session: str | None = Cookie(default=None),
) -> dict[str, object]:
    user = _require_user(amos_session)
    if not _square_ready():
        raise HTTPException(status_code=503, detail="Cash App Pay is not configured")
    with _connect() as db:
        order = create_payment_order(
            db,
            user_id=int(user["id"]),
            provider="cash_app",
        )
        return {
            **_order_payload(db, order),
            "reference_id": order["public_id"],
        }


@router.post("/instant/cash-app/complete")
def complete_cash_app_payment(
    body: CashAppPaymentRequest,
    amos_session: str | None = Cookie(default=None),
) -> dict[str, object]:
    user = _require_user(amos_session)
    if not _square_ready():
        raise HTTPException(status_code=503, detail="Cash App Pay is not configured")
    settings = _square_settings()

    with _connect() as db:
        order = _validate_order_for_payment(
            get_payment_order(db, body.order_id, user_id=int(user["id"])),
            provider="cash_app",
        )
        if order["status"] == "completed":
            return _order_payload(db, order)

    request_body = {
        "source_id": body.source_id,
        "idempotency_key": body.order_id,
        "amount_money": {
            "amount": int(order["amount_cents"]),
            "currency": order["currency"],
        },
        "location_id": settings["location_id"],
        "reference_id": body.order_id,
        "note": f"Amosclaud Full Package access for {instant_access_days()} days",
        "autocomplete": True,
    }
    try:
        response = httpx.post(
            f"{_square_api_base()}/v2/payments",
            headers={
                "Authorization": f"Bearer {settings['access_token']}",
                "Content-Type": "application/json",
                "Square-Version": settings["api_version"],
            },
            json=request_body,
            timeout=30,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail="Square could not be reached. Retry this payment safely.",
        ) from exc

    try:
        payload = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Square returned an invalid response") from exc
    if response.status_code >= 400:
        errors = payload.get("errors") or []
        detail = errors[0].get("detail") if errors else None
        raise HTTPException(
            status_code=402 if response.status_code < 500 else 502,
            detail=detail or "Cash App payment was not completed",
        )

    payment = payload.get("payment") or {}
    payment_id = str(payment.get("id") or "")
    if not payment_id:
        raise HTTPException(status_code=502, detail="Square did not return a payment ID")

    try:
        with _connect() as db:
            order = _validate_order_for_payment(
                get_payment_order(db, body.order_id, user_id=int(user["id"])),
                provider="cash_app",
            )
            _validate_square_payment(order, payment)
            status = str(payment.get("status") or "").upper()
            update_payment_order(
                db,
                body.order_id,
                status="processing" if status == "APPROVED" else "pending",
                provider_payment_id=payment_id,
            )
            if status == "COMPLETED":
                grant_payment_entitlement(
                    db,
                    public_id=body.order_id,
                    provider_payment_id=payment_id,
                )
            elif status in {"FAILED", "CANCELED"}:
                update_payment_order(db, body.order_id, status="failed")
            updated = get_payment_order(db, body.order_id)
            if not updated:
                raise ValueError("Payment order disappeared")
            return _order_payload(db, updated)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/instant/bitcoin/start")
def start_bitcoin_payment(
    amos_session: str | None = Cookie(default=None),
) -> dict[str, object]:
    user = _require_user(amos_session)
    if not _btcpay_ready():
        raise HTTPException(status_code=503, detail="Bitcoin checkout is not configured")
    settings = _btcpay_settings()

    with _connect() as db:
        order = create_payment_order(
            db,
            user_id=int(user["id"]),
            provider="bitcoin",
        )

    return_url = f"{_public_base_url()}/plans?payment=bitcoin&payment_order={order['public_id']}"
    request_body = {
        "amount": amount_display(),
        "currency": "USD",
        "metadata": {
            "orderId": order["public_id"],
            "itemDesc": f"Amosclaud Full Package access for {instant_access_days()} days",
        },
        "checkout": {
            "redirectURL": return_url,
            "redirectAutomatically": True,
        },
    }
    try:
        response = httpx.post(
            f"{settings['server_url']}/api/v1/stores/{settings['store_id']}/invoices",
            headers={
                "Authorization": f"token {settings['api_key']}",
                "Content-Type": "application/json",
            },
            json=request_body,
            timeout=30,
        )
    except httpx.HTTPError as exc:
        with _connect() as db:
            update_payment_order(db, order["public_id"], status="failed")
        raise HTTPException(
            status_code=502,
            detail="Bitcoin checkout could not be created",
        ) from exc

    try:
        payload = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="BTCPay returned an invalid response") from exc
    if response.status_code >= 400:
        with _connect() as db:
            update_payment_order(db, order["public_id"], status="failed")
        detail = payload.get("message") if isinstance(payload, dict) else None
        raise HTTPException(
            status_code=502,
            detail=detail or "Bitcoin checkout could not be created",
        )

    invoice_id = str(payload.get("id") or "")
    checkout_url = str(payload.get("checkoutLink") or "")
    if not invoice_id or not checkout_url:
        with _connect() as db:
            update_payment_order(db, order["public_id"], status="failed")
        raise HTTPException(
            status_code=502,
            detail="BTCPay did not return a valid invoice",
        )
    with _connect() as db:
        updated = update_payment_order(
            db,
            order["public_id"],
            provider_payment_id=invoice_id,
            provider_checkout_url=checkout_url,
        )
        return {
            **_order_payload(db, updated),
            "url": checkout_url,
        }


@router.get("/instant/orders/{order_id}")
def instant_order_status(
    order_id: str,
    amos_session: str | None = Cookie(default=None),
) -> dict[str, object]:
    user = _require_user(amos_session)
    with _connect() as db:
        order = get_payment_order(db, order_id, user_id=int(user["id"]))
        if not order:
            raise HTTPException(status_code=404, detail="Payment order not found")
        return _order_payload(db, order)


@router.post("/webhooks/square", include_in_schema=False)
async def square_payment_webhook(
    request: Request,
    signature: str | None = Header(
        default=None,
        alias="X-Square-HmacSha256-Signature",
    ),
) -> dict[str, bool]:
    raw_body = await request.body()
    if not _verify_square_signature(raw_body, signature):
        raise HTTPException(status_code=403, detail="Invalid Square webhook signature")
    try:
        event = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid Square webhook body") from exc

    event_id = str(event.get("event_id") or "")
    event_type = str(event.get("type") or "")
    if not event_id or not event_type:
        raise HTTPException(status_code=400, detail="Square webhook is missing event data")
    settings = _square_settings()
    if settings["merchant_id"] and event.get("merchant_id") != settings["merchant_id"]:
        raise HTTPException(status_code=403, detail="Square merchant does not match Amosclaud")

    with _connect() as db:
        if _event_seen(db, "square", event_id):
            return {"received": True}

        obj = ((event.get("data") or {}).get("object") or {})
        if event_type in {"payment.created", "payment.updated"}:
            payment = obj.get("payment") or {}
            order = _square_payment_order(db, payment)
            if order:
                try:
                    _validate_square_payment(order, payment)
                except ValueError as exc:
                    raise HTTPException(status_code=400, detail=str(exc)) from exc
                payment_id = str(payment.get("id") or "")
                status = str(payment.get("status") or "").upper()
                if payment_id:
                    update_payment_order(
                        db,
                        order["public_id"],
                        provider_payment_id=payment_id,
                        status="processing" if status == "APPROVED" else order["status"],
                    )
                if status == "COMPLETED" and payment_id:
                    grant_payment_entitlement(
                        db,
                        public_id=order["public_id"],
                        provider_payment_id=payment_id,
                    )
                elif status in {"FAILED", "CANCELED"}:
                    update_payment_order(db, order["public_id"], status="failed")
        elif event_type in {"refund.created", "refund.updated"}:
            refund = obj.get("refund") or {}
            if str(refund.get("status") or "").upper() == "COMPLETED":
                payment_id = str(refund.get("payment_id") or "")
                if payment_id:
                    revoke_payment_entitlement(
                        db,
                        provider="cash_app",
                        provider_payment_id=payment_id,
                    )

        _mark_event(
            db,
            provider="square",
            event_id=event_id,
            event_type=event_type,
        )
    return {"received": True}


@router.post("/webhooks/btcpay", include_in_schema=False)
async def btcpay_payment_webhook(
    request: Request,
    signature: str | None = Header(default=None, alias="BTCPay-Sig"),
) -> dict[str, bool]:
    raw_body = await request.body()
    if not _verify_btcpay_signature(raw_body, signature):
        raise HTTPException(status_code=403, detail="Invalid BTCPay webhook signature")
    try:
        event = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid BTCPay webhook body") from exc

    event_id = str(event.get("deliveryId") or "")
    event_type = str(event.get("type") or "")
    invoice_id = str(event.get("invoiceId") or "")
    settings = _btcpay_settings()
    if not event_id or not event_type or not invoice_id:
        raise HTTPException(status_code=400, detail="BTCPay webhook is missing event data")
    if str(event.get("storeId") or "") != settings["store_id"]:
        raise HTTPException(status_code=403, detail="BTCPay store does not match Amosclaud")

    with _connect() as db:
        if _event_seen(db, "btcpay", event_id):
            return {"received": True}
        order = get_provider_order(
            db,
            provider="bitcoin",
            provider_payment_id=invoice_id,
        )
        if order:
            if event_type == "InvoiceSettled":
                grant_payment_entitlement(
                    db,
                    public_id=order["public_id"],
                    provider_payment_id=invoice_id,
                )
            elif event_type == "InvoiceProcessing":
                update_payment_order(db, order["public_id"], status="processing")
            elif event_type in {"InvoiceExpired", "InvoiceInvalid"}:
                update_payment_order(db, order["public_id"], status="failed")

        _mark_event(
            db,
            provider="btcpay",
            event_id=event_id,
            event_type=event_type,
        )
    return {"received": True}

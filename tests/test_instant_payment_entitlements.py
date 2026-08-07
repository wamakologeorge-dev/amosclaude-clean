import base64
import hashlib
import hmac
import sqlite3
from datetime import datetime, timedelta, timezone

from amoscloud_ai.api.routes import instant_payments
from amoscloud_ai.payment_entitlements import (
    active_time_entitlement,
    create_payment_order,
    grant_payment_entitlement,
)


def database() -> sqlite3.Connection:
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("CREATE TABLE users(id INTEGER PRIMARY KEY)")
    db.execute("INSERT INTO users(id) VALUES (1)")
    return db


def test_payment_grant_is_idempotent_and_a_new_payment_extends_time(monkeypatch) -> None:
    monkeypatch.setenv("AMOSCLAUD_INSTANT_ACCESS_DAYS", "30")
    db = database()
    first = create_payment_order(db, user_id=1, provider="cash_app")
    granted = grant_payment_entitlement(
        db,
        public_id=first["public_id"],
        provider_payment_id="square-payment-1",
    )
    first_expiry = datetime.fromisoformat(granted["expires_at"])

    replay = grant_payment_entitlement(
        db,
        public_id=first["public_id"],
        provider_payment_id="square-payment-1",
    )
    assert replay["expires_at"] == granted["expires_at"]

    second = create_payment_order(db, user_id=1, provider="bitcoin")
    extended = grant_payment_entitlement(
        db,
        public_id=second["public_id"],
        provider_payment_id="btcpay-invoice-2",
    )
    second_expiry = datetime.fromisoformat(extended["expires_at"])
    assert second_expiry >= first_expiry + timedelta(days=30)


def test_expired_payment_access_auto_locks(monkeypatch) -> None:
    monkeypatch.setenv("AMOSCLAUD_INSTANT_ACCESS_DAYS", "1")
    db = database()
    order = create_payment_order(db, user_id=1, provider="bitcoin")
    grant_payment_entitlement(
        db,
        public_id=order["public_id"],
        provider_payment_id="btcpay-expired",
    )
    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    db.execute(
        "UPDATE billing_time_entitlements SET expires_at=? WHERE user_id=1",
        (past,),
    )
    db.commit()
    assert active_time_entitlement(db, 1) is None
    row = db.execute(
        "SELECT status FROM billing_time_entitlements WHERE user_id=1"
    ).fetchone()
    assert row["status"] == "expired"


def test_square_and_btcpay_webhook_signatures(monkeypatch) -> None:
    body = b'{"event_id":"event-1"}'
    notification_url = "https://www.amosclaud.com/api/v1/billing/webhooks/square"
    monkeypatch.setenv("SQUARE_WEBHOOK_SIGNATURE_KEY", "square-secret")
    monkeypatch.setenv("SQUARE_WEBHOOK_NOTIFICATION_URL", notification_url)
    square_digest = hmac.new(
        b"square-secret",
        notification_url.encode() + body,
        hashlib.sha256,
    ).digest()
    square_signature = base64.b64encode(square_digest).decode()
    assert instant_payments._verify_square_signature(body, square_signature)
    assert not instant_payments._verify_square_signature(body, "wrong")

    monkeypatch.setenv("BTCPAY_WEBHOOK_SECRET", "bitcoin-secret")
    btcpay_signature = "sha256=" + hmac.new(
        b"bitcoin-secret", body, hashlib.sha256
    ).hexdigest()
    assert instant_payments._verify_btcpay_signature(body, btcpay_signature)
    assert not instant_payments._verify_btcpay_signature(body, "sha256=wrong")

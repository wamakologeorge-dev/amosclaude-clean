"""Time-limited Full Package entitlements granted by verified one-time payments."""

from __future__ import annotations

import os
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

DEFAULT_PRICE_CENTS = 1500
DEFAULT_ACCESS_DAYS = 30
DEFAULT_ORDER_MINUTES = 20
ACTIVE_PAYMENT_STATUSES = {"active"}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utcnow().isoformat()


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _bounded_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if value < minimum or value > maximum:
        raise RuntimeError(f"{name} must be between {minimum} and {maximum}")
    return value


def instant_price_cents() -> int:
    return _bounded_int("AMOSCLAUD_INSTANT_PRICE_CENTS", DEFAULT_PRICE_CENTS, 100, 100_000)


def instant_access_days() -> int:
    return _bounded_int("AMOSCLAUD_INSTANT_ACCESS_DAYS", DEFAULT_ACCESS_DAYS, 1, 3650)


def order_lifetime_minutes() -> int:
    return _bounded_int("AMOSCLAUD_PAYMENT_ORDER_MINUTES", DEFAULT_ORDER_MINUTES, 5, 120)


def amount_display() -> str:
    return f"{instant_price_cents() / 100:.2f}"


def ensure_payment_schema(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS billing_payment_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            public_id TEXT NOT NULL UNIQUE,
            user_id INTEGER NOT NULL,
            provider TEXT NOT NULL,
            amount_cents INTEGER NOT NULL,
            currency TEXT NOT NULL DEFAULT 'USD',
            status TEXT NOT NULL DEFAULT 'pending',
            provider_payment_id TEXT UNIQUE,
            provider_checkout_url TEXT,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            completed_at TEXT,
            refunded_at TEXT,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_billing_payment_orders_user
            ON billing_payment_orders(user_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_billing_payment_orders_provider
            ON billing_payment_orders(provider, provider_payment_id);

        CREATE TABLE IF NOT EXISTS billing_time_entitlements (
            user_id INTEGER PRIMARY KEY,
            provider TEXT NOT NULL,
            provider_payment_id TEXT NOT NULL UNIQUE,
            order_public_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            starts_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            amount_cents INTEGER NOT NULL,
            currency TEXT NOT NULL DEFAULT 'USD',
            updated_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS billing_instant_webhook_events (
            provider TEXT NOT NULL,
            event_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            processed_at TEXT NOT NULL,
            PRIMARY KEY(provider, event_id)
        );
        """
    )
    db.commit()


def create_payment_order(
    db: sqlite3.Connection,
    *,
    user_id: int,
    provider: str,
) -> sqlite3.Row:
    ensure_payment_schema(db)
    now = utcnow()
    public_id = "amospay_" + secrets.token_urlsafe(18)
    expires_at = now + timedelta(minutes=order_lifetime_minutes())
    db.execute(
        """
        INSERT INTO billing_payment_orders(
            public_id,user_id,provider,amount_cents,currency,status,
            created_at,expires_at,updated_at
        ) VALUES (?,?,?,?,?,'pending',?,?,?)
        """,
        (
            public_id,
            user_id,
            provider,
            instant_price_cents(),
            "USD",
            now.isoformat(),
            expires_at.isoformat(),
            now.isoformat(),
        ),
    )
    db.commit()
    return db.execute(
        "SELECT * FROM billing_payment_orders WHERE public_id=?",
        (public_id,),
    ).fetchone()


def get_payment_order(
    db: sqlite3.Connection,
    public_id: str,
    *,
    user_id: int | None = None,
) -> sqlite3.Row | None:
    ensure_payment_schema(db)
    if user_id is None:
        return db.execute(
            "SELECT * FROM billing_payment_orders WHERE public_id=?",
            (public_id,),
        ).fetchone()
    return db.execute(
        "SELECT * FROM billing_payment_orders WHERE public_id=? AND user_id=?",
        (public_id, user_id),
    ).fetchone()


def get_provider_order(
    db: sqlite3.Connection,
    *,
    provider: str,
    provider_payment_id: str | None = None,
    public_id: str | None = None,
) -> sqlite3.Row | None:
    ensure_payment_schema(db)
    if provider_payment_id:
        row = db.execute(
            """
            SELECT * FROM billing_payment_orders
            WHERE provider=? AND provider_payment_id=?
            """,
            (provider, provider_payment_id),
        ).fetchone()
        if row:
            return row
    if public_id:
        return db.execute(
            """
            SELECT * FROM billing_payment_orders
            WHERE provider=? AND public_id=?
            """,
            (provider, public_id),
        ).fetchone()
    return None


def update_payment_order(
    db: sqlite3.Connection,
    public_id: str,
    *,
    status: str | None = None,
    provider_payment_id: str | None = None,
    provider_checkout_url: str | None = None,
) -> sqlite3.Row:
    ensure_payment_schema(db)
    row = get_payment_order(db, public_id)
    if not row:
        raise ValueError("Payment order not found")
    fields: list[str] = ["updated_at=?"]
    values: list[Any] = [iso_now()]
    if status is not None:
        fields.append("status=?")
        values.append(status)
    if provider_payment_id is not None:
        fields.append("provider_payment_id=?")
        values.append(provider_payment_id)
    if provider_checkout_url is not None:
        fields.append("provider_checkout_url=?")
        values.append(provider_checkout_url)
    values.append(public_id)
    db.execute(
        f"UPDATE billing_payment_orders SET {','.join(fields)} WHERE public_id=?",
        values,
    )
    db.commit()
    return get_payment_order(db, public_id)


def grant_payment_entitlement(
    db: sqlite3.Connection,
    *,
    public_id: str,
    provider_payment_id: str,
) -> sqlite3.Row:
    """Grant or extend access exactly once for a completed payment order."""

    ensure_payment_schema(db)
    order = get_payment_order(db, public_id)
    if not order:
        raise ValueError("Payment order not found")
    if order["provider_payment_id"] and order["provider_payment_id"] != provider_payment_id:
        raise ValueError("Payment order is already linked to another provider payment")

    existing = db.execute(
        "SELECT * FROM billing_time_entitlements WHERE user_id=?",
        (order["user_id"],),
    ).fetchone()
    if order["status"] == "completed":
        if not existing:
            raise ValueError("Completed payment order is missing its entitlement")
        return existing

    now = utcnow()
    current_expiry = parse_iso(existing["expires_at"]) if existing else None
    base = current_expiry if current_expiry and current_expiry > now else now
    expires_at = base + timedelta(days=instant_access_days())
    now_iso = now.isoformat()

    db.execute(
        """
        UPDATE billing_payment_orders
        SET status='completed',provider_payment_id=?,completed_at=?,
            updated_at=?
        WHERE public_id=?
        """,
        (provider_payment_id, now_iso, now_iso, public_id),
    )
    db.execute(
        """
        INSERT INTO billing_time_entitlements(
            user_id,provider,provider_payment_id,order_public_id,status,
            starts_at,expires_at,amount_cents,currency,updated_at
        ) VALUES (?,?,?,?, 'active',?,?,?,?,?)
        ON CONFLICT(user_id) DO UPDATE SET
            provider=excluded.provider,
            provider_payment_id=excluded.provider_payment_id,
            order_public_id=excluded.order_public_id,
            status='active',
            starts_at=excluded.starts_at,
            expires_at=excluded.expires_at,
            amount_cents=excluded.amount_cents,
            currency=excluded.currency,
            updated_at=excluded.updated_at
        """,
        (
            order["user_id"],
            order["provider"],
            provider_payment_id,
            public_id,
            now_iso,
            expires_at.isoformat(),
            order["amount_cents"],
            order["currency"],
            now_iso,
        ),
    )
    db.commit()
    return db.execute(
        "SELECT * FROM billing_time_entitlements WHERE user_id=?",
        (order["user_id"],),
    ).fetchone()


def revoke_payment_entitlement(
    db: sqlite3.Connection,
    *,
    provider: str,
    provider_payment_id: str,
    status: str = "refunded",
) -> None:
    ensure_payment_schema(db)
    order = get_provider_order(
        db,
        provider=provider,
        provider_payment_id=provider_payment_id,
    )
    if not order:
        return
    now_iso = iso_now()
    db.execute(
        """
        UPDATE billing_payment_orders
        SET status=?,refunded_at=?,updated_at=?
        WHERE id=?
        """,
        (status, now_iso, now_iso, order["id"]),
    )
    current = db.execute(
        "SELECT * FROM billing_time_entitlements WHERE user_id=?",
        (order["user_id"],),
    ).fetchone()
    if current and current["order_public_id"] == order["public_id"]:
        db.execute(
            """
            UPDATE billing_time_entitlements
            SET status=?,expires_at=?,updated_at=?
            WHERE user_id=?
            """,
            (status, now_iso, now_iso, order["user_id"]),
        )
    db.commit()


def active_time_entitlement(
    db: sqlite3.Connection,
    user_id: int,
) -> dict[str, object] | None:
    ensure_payment_schema(db)
    row = db.execute(
        "SELECT * FROM billing_time_entitlements WHERE user_id=?",
        (user_id,),
    ).fetchone()
    if not row or row["status"] not in ACTIVE_PAYMENT_STATUSES:
        return None
    expires_at = parse_iso(row["expires_at"])
    if not expires_at or expires_at <= utcnow():
        db.execute(
            """
            UPDATE billing_time_entitlements
            SET status='expired',updated_at=?
            WHERE user_id=? AND status='active'
            """,
            (iso_now(), user_id),
        )
        db.commit()
        return None
    remaining_seconds = max(0, int((expires_at - utcnow()).total_seconds()))
    return {
        "provider": row["provider"],
        "provider_payment_id": row["provider_payment_id"],
        "order_public_id": row["order_public_id"],
        "status": row["status"],
        "starts_at": row["starts_at"],
        "expires_at": row["expires_at"],
        "remaining_seconds": remaining_seconds,
        "amount_cents": row["amount_cents"],
        "currency": row["currency"],
    }


def record_webhook_event(
    db: sqlite3.Connection,
    *,
    provider: str,
    event_id: str,
    event_type: str,
) -> bool:
    """Return False when an event was already processed."""

    ensure_payment_schema(db)
    if db.execute(
        """
        SELECT 1 FROM billing_instant_webhook_events
        WHERE provider=? AND event_id=?
        """,
        (provider, event_id),
    ).fetchone():
        return False
    db.execute(
        """
        INSERT INTO billing_instant_webhook_events(
            provider,event_id,event_type,processed_at
        ) VALUES (?,?,?,?)
        """,
        (provider, event_id, event_type, iso_now()),
    )
    db.commit()
    return True

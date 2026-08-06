"""Amosclaud API credentials and prepaid agent-credit accounting."""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
from datetime import datetime, timezone

VERIFIED_PAYMENT_REASONS = ("cash_app_payment", "bitcoin_payment")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def key_hash(value: str) -> str:
    return hashlib.sha256(value.strip().encode()).hexdigest()


def ensure_agent_schema(db: sqlite3.Connection) -> None:
    db.executescript("""
        CREATE TABLE IF NOT EXISTS agent_api_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            key_hash TEXT NOT NULL UNIQUE,
            key_prefix TEXT NOT NULL,
            label TEXT NOT NULL,
            created_at TEXT NOT NULL,
            last_used_at TEXT,
            revoked_at TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS agent_token_wallets (
            user_id INTEGER PRIMARY KEY,
            balance INTEGER NOT NULL DEFAULT 0 CHECK(balance>=0),
            updated_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS agent_token_ledger (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            delta INTEGER NOT NULL,
            reason TEXT NOT NULL,
            reference TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(reason, reference),
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS agent_billing_customers (
            user_id INTEGER PRIMARY KEY,
            stripe_customer_id TEXT NOT NULL UNIQUE,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        """)
    db.commit()


def has_verified_api_payment(db: sqlite3.Connection, user_id: int) -> bool:
    """Return whether Cash App or Bitcoin payment activated this account's API."""

    ensure_agent_schema(db)
    placeholders = ",".join("?" for _ in VERIFIED_PAYMENT_REASONS)
    row = db.execute(
        f"""SELECT 1 FROM agent_token_ledger
            WHERE user_id=? AND reason IN ({placeholders}) LIMIT 1""",
        (user_id, *VERIFIED_PAYMENT_REASONS),
    ).fetchone()
    return bool(row)


def api_access_is_activated(
    db: sqlite3.Connection,
    user_id: int,
    *,
    is_admin: bool = False,
) -> bool:
    """Allow the platform owner or an account with a verified paid activation."""

    return bool(is_admin) or has_verified_api_payment(db, user_id)


def issue_api_key(db: sqlite3.Connection, user_id: int, label: str) -> tuple[int, str, str]:
    ensure_agent_schema(db)
    raw = "amos_live_" + secrets.token_urlsafe(32)
    prefix = raw[:16]
    cursor = db.execute(
        "INSERT INTO agent_api_keys(user_id,key_hash,key_prefix,label,created_at) VALUES (?,?,?,?,?)",
        (user_id, key_hash(raw), prefix, label, now()),
    )
    db.commit()
    return int(cursor.lastrowid), raw, prefix


def credit_tokens(
    db: sqlite3.Connection,
    user_id: int,
    amount: int,
    *,
    reason: str,
    reference: str,
) -> bool:
    if amount <= 0:
        raise ValueError("Token credit amount must be positive")
    ensure_agent_schema(db)
    try:
        db.execute(
            "INSERT INTO agent_token_ledger(user_id,delta,reason,reference,created_at) VALUES (?,?,?,?,?)",
            (user_id, amount, reason, reference, now()),
        )
    except sqlite3.IntegrityError:
        return False
    db.execute(
        """INSERT INTO agent_token_wallets(user_id,balance,updated_at) VALUES (?,?,?)
           ON CONFLICT(user_id) DO UPDATE SET balance=balance+excluded.balance,updated_at=excluded.updated_at""",
        (user_id, amount, now()),
    )
    db.commit()
    return True


def debit_tokens(
    db: sqlite3.Connection,
    user_id: int,
    amount: int,
    *,
    reference: str,
) -> bool:
    if amount <= 0:
        raise ValueError("Token debit amount must be positive")
    ensure_agent_schema(db)
    cursor = db.execute(
        "UPDATE agent_token_wallets SET balance=balance-?,updated_at=? WHERE user_id=? AND balance>=?",
        (amount, now(), user_id, amount),
    )
    if cursor.rowcount != 1:
        db.rollback()
        return False
    db.execute(
        "INSERT INTO agent_token_ledger(user_id,delta,reason,reference,created_at) VALUES (?,?,'agent_request',?,?)",
        (user_id, -amount, reference, now()),
    )
    db.commit()
    return True

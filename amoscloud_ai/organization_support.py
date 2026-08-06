"""Verified organization support contributions and hosted working-time enforcement."""

from __future__ import annotations

import hashlib
import hmac
import math
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from html import escape
from typing import Any

from fastapi import APIRouter, Cookie, HTTPException
from fastapi.responses import HTMLResponse

from amoscloud_ai.api.routes.auth import _connect, get_user_from_session

api_router = APIRouter(prefix="/support-time", tags=["organization-support"])
page_router = APIRouter(tags=["organization-support"])

PAYMENT_LINKS = {
    "cash_app": "https://cash.app/$kenjamakulu",
    "bitcoin": "https://cash.app/launch/bitcoin/$kenjamakulu/pPi5bQWHLA",
}
VERIFIED_SUPPORT_REASONS = ("cash_app_payment", "bitcoin_payment")

_DEFAULT_TIER_SECONDS = {
    "starter": 10 * 60 * 60,
    "builder": 60 * 60 * 60,
    "studio": 240 * 60 * 60,
}
_CREDIT_PACKS = {
    1_000: "starter",
    5_000: "builder",
    15_000: "studio",
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def support_seconds_for_pack(pack: str) -> int:
    name = pack.strip().lower()
    if name not in _DEFAULT_TIER_SECONDS:
        raise ValueError("Unknown organization support tier")
    env_name = f"AMOSCLAUD_SUPPORT_{name.upper()}_SECONDS"
    raw = os.getenv(env_name, str(_DEFAULT_TIER_SECONDS[name])).strip()
    try:
        seconds = int(raw)
    except ValueError as exc:
        raise ValueError(f"{env_name} must be an integer") from exc
    if seconds <= 0:
        raise ValueError(f"{env_name} must be positive")
    return seconds


def support_seconds_for_credit_amount(credits: int) -> int:
    try:
        pack = _CREDIT_PACKS[int(credits)]
    except (KeyError, ValueError) as exc:
        raise ValueError("Verified payment does not match an Amosclaud support tier") from exc
    return support_seconds_for_pack(pack)


def tool_seconds_per_operation() -> int:
    raw = os.getenv("AMOSCLAUD_TOOL_SECONDS_PER_OPERATION", "60").strip()
    try:
        seconds = int(raw)
    except ValueError:
        seconds = 60
    return max(1, min(seconds, 24 * 60 * 60))


def support_tiers() -> list[dict[str, object]]:
    credits = {value: key for key, value in _CREDIT_PACKS.items()}
    return [
        {
            "id": pack,
            "name": pack.title(),
            "credits": credits[pack],
            "working_seconds": support_seconds_for_pack(pack),
            "working_hours": round(support_seconds_for_pack(pack) / 3600, 2),
        }
        for pack in ("starter", "builder", "studio")
    ]


def ensure_support_schema(db: sqlite3.Connection) -> None:
    db.executescript("""
        CREATE TABLE IF NOT EXISTS organization_support_wallets (
            user_id INTEGER PRIMARY KEY,
            remaining_seconds INTEGER NOT NULL DEFAULT 0 CHECK(remaining_seconds>=0),
            lifetime_seconds INTEGER NOT NULL DEFAULT 0 CHECK(lifetime_seconds>=0),
            updated_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS organization_support_ledger (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            delta_seconds INTEGER NOT NULL,
            reason TEXT NOT NULL,
            reference TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_support_ledger_user
            ON organization_support_ledger(user_id, id DESC);
        """)
    db.commit()


def add_verified_support_time(
    db: sqlite3.Connection,
    user_id: int,
    seconds: int,
    *,
    reason: str,
    reference: str,
) -> None:
    """Add verified support time inside the caller's current transaction."""

    if reason not in VERIFIED_SUPPORT_REASONS:
        raise ValueError("Support time requires a verified Cash App or Bitcoin payment")
    if seconds <= 0:
        raise ValueError("Support time must be positive")
    payment_reference = reference.strip()
    if not payment_reference:
        raise ValueError("A verified payment reference is required")
    db.execute(
        """INSERT INTO organization_support_ledger(
               user_id,delta_seconds,reason,reference,created_at
           ) VALUES (?,?,?,?,?)""",
        (user_id, seconds, reason, payment_reference, now()),
    )
    db.execute(
        """INSERT INTO organization_support_wallets(
               user_id,remaining_seconds,lifetime_seconds,updated_at
           ) VALUES (?,?,?,?)
           ON CONFLICT(user_id) DO UPDATE SET
             remaining_seconds=remaining_seconds+excluded.remaining_seconds,
             lifetime_seconds=lifetime_seconds+excluded.lifetime_seconds,
             updated_at=excluded.updated_at""",
        (user_id, seconds, seconds, now()),
    )


def support_wallet(db: sqlite3.Connection, user_id: int) -> dict[str, int]:
    ensure_support_schema(db)
    row = db.execute(
        """SELECT remaining_seconds,lifetime_seconds
           FROM organization_support_wallets WHERE user_id=?""",
        (user_id,),
    ).fetchone()
    if not row:
        return {"remaining_seconds": 0, "lifetime_seconds": 0}
    return {
        "remaining_seconds": int(row["remaining_seconds"]),
        "lifetime_seconds": int(row["lifetime_seconds"]),
    }


def support_time_is_active(
    db: sqlite3.Connection,
    user_id: int,
    *,
    is_admin: bool = False,
) -> bool:
    if is_admin:
        return True
    return support_wallet(db, user_id)["remaining_seconds"] > 0


def debit_support_time(
    db: sqlite3.Connection,
    user_id: int,
    seconds: int,
    *,
    reference: str | None = None,
) -> tuple[bool, int]:
    """Debit one hosted-tool time unit atomically and return the remaining time."""

    if seconds <= 0:
        raise ValueError("Support-time debit must be positive")
    ensure_support_schema(db)
    operation_reference = reference or f"tool-time:{uuid.uuid4().hex}"
    cursor = db.execute(
        """UPDATE organization_support_wallets
           SET remaining_seconds=remaining_seconds-?,updated_at=?
           WHERE user_id=? AND remaining_seconds>=?""",
        (seconds, now(), user_id, seconds),
    )
    if cursor.rowcount != 1:
        db.rollback()
        remaining = support_wallet(db, user_id)["remaining_seconds"]
        return False, remaining
    db.execute(
        """INSERT INTO organization_support_ledger(
               user_id,delta_seconds,reason,reference,created_at
           ) VALUES (?,?,'hosted_tool_time',?,?)""",
        (user_id, -seconds, operation_reference, now()),
    )
    remaining_row = db.execute(
        "SELECT remaining_seconds FROM organization_support_wallets WHERE user_id=?",
        (user_id,),
    ).fetchone()
    db.commit()
    return True, int(remaining_row["remaining_seconds"])


def _key_hash(raw: str) -> str:
    return hashlib.sha256(raw.strip().encode()).hexdigest()


def bearer_identity(raw: str) -> dict[str, Any] | None:
    """Resolve an owner key or customer Amosclaud key to a support identity."""

    supplied = raw.strip()
    if not supplied:
        return None
    owner_key = (
        os.getenv("AMOSCLAUD_MCP_ACCESS_KEY")
        or os.getenv("AMOSCLAUD_AUTONOMOUS_KEY")
        or os.getenv("AMOSCLAUD_OWNER_KEY")
        or ""
    ).strip()
    if owner_key and hmac.compare_digest(supplied, owner_key):
        return {"user_id": 0, "is_admin": True, "key_type": "owner"}

    with _connect() as db:
        try:
            from amoscloud_ai.agent_tokens import ensure_agent_schema

            ensure_agent_schema(db)
            row = db.execute(
                """SELECT k.user_id,u.is_admin,'provider' AS key_type
                   FROM agent_api_keys k
                   JOIN users u ON u.id=k.user_id
                   WHERE k.key_hash=? AND k.revoked_at IS NULL""",
                (_key_hash(supplied),),
            ).fetchone()
            if row:
                return dict(row)
            row = db.execute(
                """SELECT k.user_id,u.is_admin,'autonomous' AS key_type
                   FROM autonomous_api_keys k
                   JOIN users u ON u.id=k.user_id
                   WHERE k.key_hash=? AND k.revoked_at IS NULL""",
                (_key_hash(supplied),),
            ).fetchone()
            return dict(row) if row else None
        except sqlite3.Error:
            return None


def session_identity(token: str | None) -> dict[str, Any] | None:
    user = get_user_from_session(token)
    if not user:
        return None
    return {
        "user_id": int(user["id"]),
        "is_admin": bool(user["is_admin"]),
        "key_type": "session",
    }


def payment_required_detail() -> dict[str, object]:
    return {
        "code": "organization_support_time_required",
        "message": (
            "Verified organization support through Cash App or Bitcoin is required "
            "before Amosclaud hosted tools can work."
        ),
        "support_url": "/organization-support",
        "payment_methods": PAYMENT_LINKS,
        "tiers": support_tiers(),
    }


@api_router.get("/status")
def support_status(amos_session: str | None = Cookie(default=None)) -> dict[str, object]:
    identity = session_identity(amos_session)
    if not identity:
        raise HTTPException(status_code=401, detail="Sign in to view organization support time")
    if identity["is_admin"]:
        return {
            "active": True,
            "administrator": True,
            "remaining_seconds": None,
            "remaining_hours": None,
            "lifetime_seconds": None,
            "tiers": support_tiers(),
            "payment_methods": PAYMENT_LINKS,
        }
    with _connect() as db:
        wallet = support_wallet(db, int(identity["user_id"]))
    return {
        "active": wallet["remaining_seconds"] > 0,
        "administrator": False,
        "remaining_seconds": wallet["remaining_seconds"],
        "remaining_hours": round(wallet["remaining_seconds"] / 3600, 2),
        "lifetime_seconds": wallet["lifetime_seconds"],
        "tiers": support_tiers(),
        "payment_methods": PAYMENT_LINKS,
    }


def _hours(seconds: int) -> str:
    hours = seconds / 3600
    return f"{math.floor(hours):,}" if hours.is_integer() else f"{hours:,.2f}"


@page_router.get("/organization-support", response_class=HTMLResponse, include_in_schema=False)
def organization_support_page() -> HTMLResponse:
    cards = "".join(f"""
        <article class="card">
          <h2>{escape(str(tier['name']))}</h2>
          <p class="hours">{_hours(int(tier['working_seconds']))} hosted hours</p>
          <p>{int(tier['credits']):,} Amosclaud agent credits</p>
          <p>Higher support provides more working time for hosted tools.</p>
          <a class="cash" href="{PAYMENT_LINKS['cash_app']}" target="_blank" rel="noopener">Support with Cash App</a>
          <a class="bitcoin" href="{PAYMENT_LINKS['bitcoin']}" target="_blank" rel="noopener">Support with Bitcoin</a>
        </article>
        """ for tier in support_tiers())
    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Organization Support · Amosclaud</title>
<style>
body{{margin:0;background:#07101d;color:#f7f9ff;font:16px/1.55 system-ui,sans-serif}}main{{max-width:1050px;margin:auto;padding:36px 20px 70px}}h1{{font-size:clamp(38px,7vw,68px);line-height:1.02}}.lead{{max-width:760px;color:#b9c5d8;font-size:20px}}.grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:18px;margin-top:30px}}.card{{background:#111d30;border:1px solid #2b3d5b;border-radius:20px;padding:24px}}.hours{{font-size:31px;font-weight:900;color:#66dfae}}a{{display:block;margin-top:12px;padding:14px;border-radius:12px;text-align:center;text-decoration:none;font-weight:850;color:white}}.cash{{background:#00a84f}}.bitcoin{{background:#f7931a;color:#171008}}.notice{{margin-top:28px;padding:18px;border-left:4px solid #ffd479;background:#172238}}@media(max-width:760px){{.grid{{grid-template-columns:1fr}}}}
</style></head><body><main>
<p><a href="/">← Amosclaud</a></p><h1>Support the organization.<br>Unlock hosted working time.</h1>
<p class="lead">Official Amosclaud cloud tools remain locked until a Cash App or Bitcoin contribution is independently verified. Larger support tiers provide more hosted working time.</p>
<div class="grid">{cards}</div>
<div class="notice"><strong>Payment verification:</strong> include the Amosclaud tier and your account email or GitHub username in the payment note. Access is activated only after an administrator verifies the transaction. Because working time is provided in exchange, describe this as an organization support contribution or service purchase—not a tax-deductible charitable donation unless the organization is legally qualified to issue such receipts.</div>
</main></body></html>"""
    return HTMLResponse(html)

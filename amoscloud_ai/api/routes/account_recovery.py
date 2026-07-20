"""Verified account recovery for Amosclaud usernames and passwords."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Cookie, HTTPException, Response
from pydantic import BaseModel, Field

from amoscloud_ai.api.routes.auth import (
    _connect,
    _hash_password,
    _normalise_email,
    get_user_from_session,
)
from amoscloud_ai.mail_delivery import MailDeliveryError, deliver_security_code

router = APIRouter(prefix="/account-recovery", tags=["account-recovery"])
CODE_MINUTES = 15
MAX_ATTEMPTS = 6


class RecoveryEmailRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=254)


class RecoveryEmailVerify(BaseModel):
    email: str = Field(..., min_length=5, max_length=254)
    code: str = Field(..., min_length=6, max_length=6, pattern=r"^[0-9]{6}$")


class RecoveryCodeRequest(BaseModel):
    recovery_email: str = Field(..., min_length=5, max_length=254)


class UsernameVerifyRequest(RecoveryCodeRequest):
    code: str = Field(..., min_length=6, max_length=6, pattern=r"^[0-9]{6}$")


class PasswordRecoveryRequest(UsernameVerifyRequest):
    password: str = Field(..., min_length=10, max_length=200)


def _prepare(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS account_recovery_emails (
            user_id INTEGER PRIMARY KEY,
            email TEXT NOT NULL UNIQUE COLLATE NOCASE,
            verified_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS account_recovery_codes (
            email TEXT NOT NULL COLLATE NOCASE,
            purpose TEXT NOT NULL CHECK(purpose IN ('recovery-email','username','password')),
            user_id INTEGER NOT NULL,
            code_hash TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            PRIMARY KEY(email, purpose),
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        """
    )
    db.commit()


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _create_code(db: sqlite3.Connection, *, email: str, purpose: str, user_id: int) -> None:
    code = f"{secrets.randbelow(1_000_000):06d}"
    now = datetime.now(timezone.utc)
    db.execute(
        """INSERT INTO account_recovery_codes(email,purpose,user_id,code_hash,expires_at,attempts,created_at)
           VALUES (?,?,?,?,?,0,?)
           ON CONFLICT(email,purpose) DO UPDATE SET user_id=excluded.user_id,
           code_hash=excluded.code_hash,expires_at=excluded.expires_at,attempts=0,
           created_at=excluded.created_at""",
        (email, purpose, user_id, _hash(code), (now + timedelta(minutes=CODE_MINUTES)).isoformat(), now.isoformat()),
    )
    db.commit()
    try:
        deliver_security_code(email, code, purpose, minutes=CODE_MINUTES)
    except MailDeliveryError as exc:
        db.execute("DELETE FROM account_recovery_codes WHERE email=? AND purpose=?", (email, purpose))
        db.commit()
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _consume_code(db: sqlite3.Connection, *, email: str, purpose: str, code: str) -> sqlite3.Row:
    row = db.execute(
        "SELECT * FROM account_recovery_codes WHERE email=? AND purpose=?",
        (email, purpose),
    ).fetchone()
    now = datetime.now(timezone.utc).isoformat()
    valid = bool(
        row
        and row["expires_at"] > now
        and int(row["attempts"]) < MAX_ATTEMPTS
        and hmac.compare_digest(row["code_hash"], _hash(code))
    )
    if not valid:
        if row:
            db.execute(
                "UPDATE account_recovery_codes SET attempts=attempts+1 WHERE email=? AND purpose=?",
                (email, purpose),
            )
            db.commit()
        raise HTTPException(status_code=400, detail="Invalid or expired verification code")
    db.execute("DELETE FROM account_recovery_codes WHERE email=? AND purpose=?", (email, purpose))
    db.commit()
    return row


def _user_for_recovery_email(db: sqlite3.Connection, email: str) -> sqlite3.Row | None:
    return db.execute(
        """SELECT users.id,users.email,users.name
           FROM account_recovery_emails
           JOIN users ON users.id=account_recovery_emails.user_id
           WHERE account_recovery_emails.email=?""",
        (email,),
    ).fetchone()


@router.post("/email/request", status_code=202)
def request_recovery_email(body: RecoveryEmailRequest, amos_session: str | None = Cookie(default=None)) -> dict:
    user = get_user_from_session(amos_session)
    if not user:
        raise HTTPException(status_code=401, detail="Sign in before adding a recovery email")
    email = _normalise_email(body.email)
    if email.endswith("@amosclaud.com"):
        raise HTTPException(status_code=422, detail="Use a separate personal or business email for account recovery")
    with _connect() as db:
        _prepare(db)
        conflict = db.execute(
            "SELECT user_id FROM account_recovery_emails WHERE email=? AND user_id!=?",
            (email, user["id"]),
        ).fetchone()
        if conflict:
            raise HTTPException(status_code=409, detail="That recovery email is already linked to another account")
        _create_code(db, email=email, purpose="recovery-email", user_id=user["id"])
    return {"message": "Amosclaud sent a verification code from no-reply@amosclaud.com"}


@router.post("/email/verify")
def verify_recovery_email(body: RecoveryEmailVerify, amos_session: str | None = Cookie(default=None)) -> dict:
    user = get_user_from_session(amos_session)
    if not user:
        raise HTTPException(status_code=401, detail="Sign in before verifying a recovery email")
    email = _normalise_email(body.email)
    with _connect() as db:
        _prepare(db)
        row = _consume_code(db, email=email, purpose="recovery-email", code=body.code)
        if int(row["user_id"]) != int(user["id"]):
            raise HTTPException(status_code=400, detail="Invalid or expired verification code")
        now = datetime.now(timezone.utc).isoformat()
        db.execute(
            """INSERT INTO account_recovery_emails(user_id,email,verified_at,created_at)
               VALUES (?,?,?,?)
               ON CONFLICT(user_id) DO UPDATE SET email=excluded.email,verified_at=excluded.verified_at""",
            (user["id"], email, now, now),
        )
        db.commit()
    return {"message": "Recovery email verified", "recovery_email": email}


@router.post("/username/request", status_code=202)
def request_username_recovery(body: RecoveryCodeRequest) -> dict:
    email = _normalise_email(body.recovery_email)
    with _connect() as db:
        _prepare(db)
        user = _user_for_recovery_email(db, email)
        if user:
            _create_code(db, email=email, purpose="username", user_id=user["id"])
    return {"message": "If that recovery email is verified, Amosclaud sent a username-recovery code"}


@router.post("/username/verify")
def verify_username_recovery(body: UsernameVerifyRequest) -> dict:
    email = _normalise_email(body.recovery_email)
    with _connect() as db:
        _prepare(db)
        row = _consume_code(db, email=email, purpose="username", code=body.code)
        user = db.execute("SELECT email,name FROM users WHERE id=?", (row["user_id"],)).fetchone()
        if not user:
            raise HTTPException(status_code=400, detail="Invalid or expired verification code")
    return {"address": user["email"], "username": user["email"].split("@", 1)[0], "name": user["name"]}


@router.post("/password/request", status_code=202)
def request_password_recovery(body: RecoveryCodeRequest) -> dict:
    email = _normalise_email(body.recovery_email)
    with _connect() as db:
        _prepare(db)
        user = _user_for_recovery_email(db, email)
        if user:
            _create_code(db, email=email, purpose="password", user_id=user["id"])
    return {"message": "If that recovery email is verified, Amosclaud sent a password-reset code"}


@router.post("/password/reset", status_code=204, response_class=Response)
def reset_password(body: PasswordRecoveryRequest) -> Response:
    email = _normalise_email(body.recovery_email)
    with _connect() as db:
        _prepare(db)
        row = _consume_code(db, email=email, purpose="password", code=body.code)
        db.execute(
            "UPDATE users SET password_hash=?,provider='password' WHERE id=?",
            (_hash_password(body.password), row["user_id"]),
        )
        db.execute("DELETE FROM sessions WHERE user_id=?", (row["user_id"],))
        db.commit()
    return Response(status_code=204)


__all__ = ["router"]

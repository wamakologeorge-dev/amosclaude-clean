"""Provider-free account verification using time-based Amos Secure Codes.

The browser shows a one-time setup key. The user stores it in any authenticator
app, which then generates rotating six-digit codes without email or SMS.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import sqlite3
import struct
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field

from amoscloud_ai.api.routes.auth import (
    _connect,
    _create_session,
    _hash_password,
    _normalise_email,
    _set_session_cookie,
    _user_response,
)

router = APIRouter(prefix="/auth", tags=["auth"])
SETUP_MINUTES = 15


class SecureCodeStartRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    email: str = Field(..., min_length=5, max_length=254)
    password: str = Field(..., min_length=10, max_length=200)


class SecureCodeVerifyRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=254)
    password: str = Field(..., min_length=10, max_length=200)
    code: str = Field(..., min_length=6, max_length=12)


class SecureResetRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=254)
    password: str = Field(..., min_length=10, max_length=200)
    code: str = Field(..., min_length=6, max_length=32)


def _prepare_tables(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS secure_code_setups (
            email TEXT PRIMARY KEY COLLATE NOCASE,
            name TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            secret TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS user_authenticators (
            user_id INTEGER PRIMARY KEY,
            secret TEXT NOT NULL,
            recovery_hashes TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        """
    )
    db.commit()


def _new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _decode_secret(secret: str) -> bytes:
    padded = secret + "=" * ((8 - len(secret) % 8) % 8)
    return base64.b32decode(padded, casefold=True)


def _totp(secret: str, counter: int) -> str:
    digest = hmac.new(_decode_secret(secret), struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = (struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF) % 1_000_000
    return f"{number:06d}"


def _valid_totp(secret: str, code: str) -> bool:
    value = "".join(ch for ch in code if ch.isdigit())
    if len(value) != 6:
        return False
    counter = int(time.time()) // 30
    return any(hmac.compare_digest(_totp(secret, counter + drift), value) for drift in (-1, 0, 1))


def _new_recovery_codes() -> list[str]:
    return [f"AMOS-{secrets.token_hex(4).upper()}" for _ in range(8)]


def _hash_recovery(code: str) -> str:
    return hashlib.sha256(code.strip().upper().encode()).hexdigest()


def _consume_recovery(db: sqlite3.Connection, user_id: int, code: str, hashes_csv: str) -> bool:
    wanted = _hash_recovery(code)
    hashes = [item for item in hashes_csv.split(",") if item]
    match = next((item for item in hashes if hmac.compare_digest(item, wanted)), None)
    if not match:
        return False
    hashes.remove(match)
    db.execute("UPDATE user_authenticators SET recovery_hashes=? WHERE user_id=?", (",".join(hashes), user_id))
    return True


@router.post("/register/secure-code/start", status_code=201)
def start_secure_code(body: SecureCodeStartRequest) -> dict:
    email = _normalise_email(body.email)
    secret = _new_secret()
    now = datetime.now(timezone.utc)
    with _connect() as db:
        _prepare_tables(db)
        if db.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
            raise HTTPException(status_code=409, detail="An account with this email already exists")
        db.execute(
            """INSERT INTO secure_code_setups(email,name,password_hash,secret,expires_at,created_at)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(email) DO UPDATE SET name=excluded.name,password_hash=excluded.password_hash,
               secret=excluded.secret,expires_at=excluded.expires_at,created_at=excluded.created_at""",
            (
                email,
                body.name.strip(),
                _hash_password(body.password),
                secret,
                (now + timedelta(minutes=SETUP_MINUTES)).isoformat(),
                now.isoformat(),
            ),
        )
        db.commit()
    label = quote(f"Amosclaud:{email}")
    issuer = quote("Amosclaud")
    uri = f"otpauth://totp/{label}?secret={secret}&issuer={issuer}&algorithm=SHA1&digits=6&period=30"
    return {
        "method": "amos-secure-code",
        "secret": secret,
        "otpauth_uri": uri,
        "expires_in_minutes": SETUP_MINUTES,
        "instructions": "Save this key in an authenticator app, then enter its six-digit code.",
    }


@router.post("/register/secure-code/verify", status_code=201)
def verify_secure_code(body: SecureCodeVerifyRequest, response: Response) -> dict:
    email = _normalise_email(body.email)
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as db:
        _prepare_tables(db)
        pending = db.execute("SELECT * FROM secure_code_setups WHERE email=?", (email,)).fetchone()
        if not pending or pending["expires_at"] <= now:
            raise HTTPException(status_code=400, detail="Setup expired. Start account creation again.")
        if not _valid_totp(pending["secret"], body.code):
            raise HTTPException(status_code=400, detail="Invalid Amos Secure Code")
        if not hmac.compare_digest(_hash_password(body.password, bytes.fromhex(pending["password_hash"].split("$")[2])), pending["password_hash"]):
            raise HTTPException(status_code=400, detail="Password does not match the signup request")
        if db.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
            raise HTTPException(status_code=409, detail="An account with this email already exists")
        first_user = db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
        cursor = db.execute(
            "INSERT INTO users(name,email,password_hash,provider,is_admin,created_at) VALUES (?,?,?,'secure-code',?,?)",
            (pending["name"], email, pending["password_hash"], int(first_user), datetime.now(timezone.utc).isoformat()),
        )
        recovery_codes = _new_recovery_codes()
        db.execute(
            "INSERT INTO user_authenticators(user_id,secret,recovery_hashes,created_at) VALUES (?,?,?,?)",
            (cursor.lastrowid, pending["secret"], ",".join(_hash_recovery(code) for code in recovery_codes), datetime.now(timezone.utc).isoformat()),
        )
        db.execute("DELETE FROM secure_code_setups WHERE email=?", (email,))
        token = _create_session(db, cursor.lastrowid)
        user = db.execute("SELECT id,name,email,is_admin,provider FROM users WHERE id=?", (cursor.lastrowid,)).fetchone()
        db.commit()
    _set_session_cookie(response, token)
    return {"user": _user_response(user).model_dump(), "recovery_codes": recovery_codes}


@router.post("/password/secure-reset", status_code=204)
def secure_reset(body: SecureResetRequest) -> None:
    email = _normalise_email(body.email)
    with _connect() as db:
        _prepare_tables(db)
        user = db.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
        if not user:
            raise HTTPException(status_code=400, detail="Invalid recovery information")
        auth = db.execute("SELECT secret,recovery_hashes FROM user_authenticators WHERE user_id=?", (user["id"],)).fetchone()
        if not auth:
            raise HTTPException(status_code=400, detail="This account does not use Amos Secure Code")
        valid = _valid_totp(auth["secret"], body.code) or _consume_recovery(db, user["id"], body.code, auth["recovery_hashes"])
        if not valid:
            raise HTTPException(status_code=400, detail="Invalid authenticator or recovery code")
        db.execute("UPDATE users SET password_hash=?,provider='secure-code' WHERE id=?", (_hash_password(body.password), user["id"]))
        db.execute("DELETE FROM sessions WHERE user_id=?", (user["id"],))
        db.commit()

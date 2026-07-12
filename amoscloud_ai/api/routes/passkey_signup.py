"""Simple provider-free signup using the device's built-in passkey confirmation."""

from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field
from webauthn import generate_registration_options, options_to_json, verify_registration_response
from webauthn.helpers import bytes_to_base64url
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from amoscloud_ai.api.routes.auth import (
    _connect,
    _create_session,
    _hash_password,
    _set_session_cookie,
    _user_response,
)

router = APIRouter(prefix="/auth", tags=["auth"])
MAIL_DOMAIN = os.getenv("AMOS_MAIL_DOMAIN", "amosclaud.com").strip().lower()
RP_ID = os.getenv("PASSKEY_RP_ID", "amosclaud.com").strip().lower()
RP_NAME = os.getenv("PASSKEY_RP_NAME", "Amosclaud")
EXPECTED_ORIGIN = os.getenv("PASSKEY_ORIGIN", "https://amosclaud.com").rstrip("/")
SETUP_MINUTES = int(os.getenv("PASSKEY_SETUP_MINUTES", "10"))
USERNAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9._-]{1,30}[a-z0-9])?$")


class PasskeyStartRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    username: str = Field(..., min_length=3, max_length=32)
    password: str = Field(..., min_length=10, max_length=200)


class PasskeyFinishRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=32)
    credential: dict


def _username(value: str) -> str:
    result = value.strip().lower()
    if not USERNAME_RE.fullmatch(result):
        raise HTTPException(status_code=422, detail="Use 3-32 lowercase letters, numbers, dots, dashes, or underscores")
    return result


def _prepare(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS passkey_signups (
            username TEXT PRIMARY KEY COLLATE NOCASE,
            name TEXT NOT NULL,
            address TEXT NOT NULL UNIQUE COLLATE NOCASE,
            password_hash TEXT NOT NULL,
            user_handle BLOB NOT NULL,
            challenge BLOB NOT NULL,
            expires_at TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS passkey_credentials (
            credential_id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            public_key BLOB NOT NULL,
            sign_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS mailboxes (
            user_id INTEGER PRIMARY KEY,
            username TEXT NOT NULL UNIQUE COLLATE NOCASE,
            address TEXT NOT NULL UNIQUE COLLATE NOCASE,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        """
    )
    db.commit()


@router.post("/register/passkey/start", status_code=201)
def start_passkey_signup(body: PasskeyStartRequest) -> dict:
    username = _username(body.username)
    address = f"{username}@{MAIL_DOMAIN}"
    now = datetime.now(timezone.utc)
    user_handle = os.urandom(32)

    with _connect() as db:
        _prepare(db)
        if db.execute("SELECT 1 FROM users WHERE email=?", (address,)).fetchone():
            raise HTTPException(status_code=409, detail="That Amosclaud username is already taken")
        if db.execute("SELECT 1 FROM mailboxes WHERE username=? OR address=?", (username, address)).fetchone():
            raise HTTPException(status_code=409, detail="That Amosclaud username is already taken")

        options = generate_registration_options(
            rp_id=RP_ID,
            rp_name=RP_NAME,
            user_id=user_handle,
            user_name=address,
            user_display_name=body.name.strip(),
            authenticator_selection=AuthenticatorSelectionCriteria(
                resident_key=ResidentKeyRequirement.PREFERRED,
                user_verification=UserVerificationRequirement.REQUIRED,
            ),
        )
        db.execute(
            """INSERT INTO passkey_signups(username,name,address,password_hash,user_handle,challenge,expires_at,created_at)
               VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(username) DO UPDATE SET name=excluded.name,address=excluded.address,
               password_hash=excluded.password_hash,user_handle=excluded.user_handle,challenge=excluded.challenge,
               expires_at=excluded.expires_at,created_at=excluded.created_at""",
            (
                username,
                body.name.strip(),
                address,
                _hash_password(body.password),
                user_handle,
                options.challenge,
                (now + timedelta(minutes=SETUP_MINUTES)).isoformat(),
                now.isoformat(),
            ),
        )
        db.commit()

    return {
        "address": address,
        "public_key": json.loads(options_to_json(options)),
        "expires_in_minutes": SETUP_MINUTES,
    }


@router.post("/register/passkey/finish", status_code=201)
def finish_passkey_signup(body: PasskeyFinishRequest, response: Response) -> dict:
    username = _username(body.username)
    now = datetime.now(timezone.utc).isoformat()

    with _connect() as db:
        _prepare(db)
        pending = db.execute("SELECT * FROM passkey_signups WHERE username=?", (username,)).fetchone()
        if not pending or pending["expires_at"] <= now:
            raise HTTPException(status_code=400, detail="Signup expired. Start again.")

        try:
            verified = verify_registration_response(
                credential=body.credential,
                expected_challenge=bytes(pending["challenge"]),
                expected_rp_id=RP_ID,
                expected_origin=EXPECTED_ORIGIN,
                require_user_verification=True,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail="Device verification failed. Try again on this device.") from exc

        if db.execute("SELECT 1 FROM users WHERE email=?", (pending["address"],)).fetchone():
            raise HTTPException(status_code=409, detail="That Amosclaud username is already taken")

        first_user = db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
        cursor = db.execute(
            "INSERT INTO users(name,email,password_hash,provider,is_admin,created_at) VALUES (?,?,?,'passkey',?,?)",
            (pending["name"], pending["address"], pending["password_hash"], int(first_user), now),
        )
        user_id = cursor.lastrowid
        db.execute(
            "INSERT INTO passkey_credentials(credential_id,user_id,public_key,sign_count,created_at) VALUES (?,?,?,?,?)",
            (
                bytes_to_base64url(verified.credential_id),
                user_id,
                verified.credential_public_key,
                verified.sign_count,
                now,
            ),
        )
        db.execute(
            "INSERT INTO mailboxes(user_id,username,address,created_at) VALUES (?,?,?,?)",
            (user_id, username, pending["address"], now),
        )
        db.execute("DELETE FROM passkey_signups WHERE username=?", (username,))
        token = _create_session(db, user_id)
        user = db.execute("SELECT id,name,email,is_admin,provider FROM users WHERE id=?", (user_id,)).fetchone()
        db.commit()

    _set_session_cookie(response, token)
    return {"user": _user_response(user).model_dump(), "address": pending["address"]}

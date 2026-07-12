"""Provider-free signup and fingerprint/passkey sign-in."""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import bytes_to_base64url
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from amoscloud_ai.api.routes.auth import (
    _connect,
    _create_session,
    _set_session_cookie,
    _token_hash,
    _user_response,
    _hash_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])
log = logging.getLogger(__name__)
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


class PasskeyLoginFinishRequest(BaseModel):
    attempt: str = Field(..., min_length=20, max_length=200)
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
        CREATE TABLE IF NOT EXISTS passkey_login_challenges (
            attempt_hash TEXT PRIMARY KEY,
            challenge BLOB NOT NULL,
            expires_at TEXT NOT NULL,
            created_at TEXT NOT NULL
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


def _request_origin(request: Request) -> str | None:
    forwarded_proto = request.headers.get("x-forwarded-proto", request.url.scheme).split(",", 1)[0].strip().lower()
    forwarded_host = request.headers.get("x-forwarded-host", request.headers.get("host", request.url.netloc)).split(",", 1)[0].strip().lower()
    hostname = forwarded_host.split(":", 1)[0]
    allowed_host = hostname == RP_ID or hostname.endswith(f".{RP_ID}")
    local_development = RP_ID in {"localhost", "127.0.0.1"} and hostname in {"localhost", "127.0.0.1"}
    if not (allowed_host or local_development):
        return None
    if forwarded_proto != "https" and not local_development:
        return None
    return f"{forwarded_proto}://{forwarded_host}".rstrip("/")


def _origins(request: Request) -> list[str]:
    values = [EXPECTED_ORIGIN]
    public_origin = _request_origin(request)
    if public_origin and public_origin not in values:
        values.append(public_origin)
    return values


def _verify_registration(credential: dict, challenge: bytes, request: Request):
    failures: list[str] = []
    for origin in _origins(request):
        try:
            return verify_registration_response(
                credential=credential,
                expected_challenge=challenge,
                expected_rp_id=RP_ID,
                expected_origin=origin,
                require_user_verification=True,
            )
        except Exception as exc:
            failures.append(f"{origin}: {type(exc).__name__}: {exc}")
    log.warning("Passkey registration rejected for RP %s; %s", RP_ID, " | ".join(failures))
    raise HTTPException(status_code=400, detail="Device verification could not be confirmed. Try again.")


def _verify_login(credential: dict, challenge: bytes, public_key: bytes, sign_count: int, request: Request):
    failures: list[str] = []
    for origin in _origins(request):
        try:
            return verify_authentication_response(
                credential=credential,
                expected_challenge=challenge,
                expected_rp_id=RP_ID,
                expected_origin=origin,
                credential_public_key=public_key,
                credential_current_sign_count=sign_count,
                require_user_verification=True,
            )
        except Exception as exc:
            failures.append(f"{origin}: {type(exc).__name__}: {exc}")
    log.warning("Passkey login rejected for RP %s; %s", RP_ID, " | ".join(failures))
    raise HTTPException(status_code=401, detail="Fingerprint or device verification failed")


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
        options = generate_registration_options(
            rp_id=RP_ID,
            rp_name=RP_NAME,
            user_id=user_handle,
            user_name=address,
            user_display_name=body.name.strip(),
            authenticator_selection=AuthenticatorSelectionCriteria(
                resident_key=ResidentKeyRequirement.REQUIRED,
                user_verification=UserVerificationRequirement.REQUIRED,
            ),
        )
        db.execute(
            """INSERT INTO passkey_signups(username,name,address,password_hash,user_handle,challenge,expires_at,created_at)
               VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(username) DO UPDATE SET name=excluded.name,address=excluded.address,
               password_hash=excluded.password_hash,user_handle=excluded.user_handle,challenge=excluded.challenge,
               expires_at=excluded.expires_at,created_at=excluded.created_at""",
            (username, body.name.strip(), address, _hash_password(body.password), user_handle, options.challenge,
             (now + timedelta(minutes=SETUP_MINUTES)).isoformat(), now.isoformat()),
        )
        db.commit()
    return {"address": address, "public_key": json.loads(options_to_json(options)), "expires_in_minutes": SETUP_MINUTES}


@router.post("/register/passkey/finish", status_code=201)
def finish_passkey_signup(body: PasskeyFinishRequest, response: Response, request: Request) -> dict:
    username = _username(body.username)
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as db:
        _prepare(db)
        pending = db.execute("SELECT * FROM passkey_signups WHERE username=?", (username,)).fetchone()
        if not pending or pending["expires_at"] <= now:
            raise HTTPException(status_code=400, detail="Signup expired. Start again.")
        verified = _verify_registration(body.credential, bytes(pending["challenge"]), request)
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
            (bytes_to_base64url(verified.credential_id), user_id, verified.credential_public_key, verified.sign_count, now),
        )
        db.execute("INSERT INTO mailboxes(user_id,username,address,created_at) VALUES (?,?,?,?)", (user_id, username, pending["address"], now))
        db.execute("DELETE FROM passkey_signups WHERE username=?", (username,))
        token = _create_session(db, user_id)
        user = db.execute("SELECT id,name,email,is_admin,provider FROM users WHERE id=?", (user_id,)).fetchone()
        db.commit()
    _set_session_cookie(response, token)
    return {"user": _user_response(user).model_dump(), "address": pending["address"]}


@router.post("/login/passkey/start")
def start_passkey_login() -> dict:
    now = datetime.now(timezone.utc)
    attempt = secrets.token_urlsafe(32)
    options = generate_authentication_options(
        rp_id=RP_ID,
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    with _connect() as db:
        _prepare(db)
        db.execute("DELETE FROM passkey_login_challenges WHERE expires_at<=?", (now.isoformat(),))
        db.execute(
            "INSERT INTO passkey_login_challenges(attempt_hash,challenge,expires_at,created_at) VALUES (?,?,?,?)",
            (_token_hash(attempt), options.challenge, (now + timedelta(minutes=5)).isoformat(), now.isoformat()),
        )
        db.commit()
    return {"attempt": attempt, "public_key": json.loads(options_to_json(options))}


@router.post("/login/passkey/finish")
def finish_passkey_login(body: PasskeyLoginFinishRequest, response: Response, request: Request) -> dict:
    credential_id = str(body.credential.get("id") or "")
    if not credential_id:
        raise HTTPException(status_code=400, detail="Missing device credential")
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as db:
        _prepare(db)
        challenge_row = db.execute(
            "SELECT * FROM passkey_login_challenges WHERE attempt_hash=? AND expires_at>?",
            (_token_hash(body.attempt), now),
        ).fetchone()
        if not challenge_row:
            raise HTTPException(status_code=400, detail="Fingerprint sign-in expired. Try again.")
        credential = db.execute(
            """SELECT passkey_credentials.*,users.id AS uid,users.name,users.email,users.is_admin,users.provider
               FROM passkey_credentials JOIN users ON users.id=passkey_credentials.user_id
               WHERE passkey_credentials.credential_id=?""",
            (credential_id,),
        ).fetchone()
        if not credential:
            raise HTTPException(status_code=401, detail="This device is not linked to an Amosclaud account")
        verified = _verify_login(
            body.credential,
            bytes(challenge_row["challenge"]),
            bytes(credential["public_key"]),
            int(credential["sign_count"]),
            request,
        )
        db.execute("UPDATE passkey_credentials SET sign_count=? WHERE credential_id=?", (verified.new_sign_count, credential_id))
        db.execute("DELETE FROM passkey_login_challenges WHERE attempt_hash=?", (_token_hash(body.attempt),))
        token = _create_session(db, credential["user_id"])
        user = db.execute("SELECT id,name,email,is_admin,provider FROM users WHERE id=?", (credential["user_id"],)).fetchone()
        db.commit()
    _set_session_cookie(response, token)
    return {"user": _user_response(user).model_dump()}

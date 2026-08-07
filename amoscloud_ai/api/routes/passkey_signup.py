"""Provider-free signup and fingerprint/passkey sign-in."""

from __future__ import annotations

import io
import json
import logging
import os
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

import qrcode
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from qrcode.image.svg import SvgPathImage
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
    _hash_password,
    _set_session_cookie,
    _token_hash,
    _user_response,
)

router = APIRouter(prefix="/auth", tags=["auth"])
log = logging.getLogger(__name__)
MAIL_DOMAIN = os.getenv("AMOS_MAIL_DOMAIN", "amosclaud.com").strip().lower()
RP_ID = os.getenv("PASSKEY_RP_ID", "amosclaud.com").strip().lower()
RP_NAME = os.getenv("PASSKEY_RP_NAME", "Amosclaud")
EXPECTED_ORIGIN = os.getenv("PASSKEY_ORIGIN", "https://amosclaud.com").rstrip("/")
SETUP_MINUTES = int(os.getenv("PASSKEY_SETUP_MINUTES", "10"))
USERNAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9._-]{1,30}[a-z0-9])?$")
WEB_DIR = Path(__file__).resolve().parents[3] / "web"
QR_CHALLENGE_SECONDS = int(os.getenv("QR_LOGIN_CHALLENGE_SECONDS", "120"))
QR_CODE_SECONDS = int(os.getenv("QR_LOGIN_CODE_SECONDS", "300"))
QR_MAX_ATTEMPTS = int(os.getenv("QR_LOGIN_MAX_ATTEMPTS", "5"))
QR_REQUEST_COOLDOWN_SECONDS = int(os.getenv("QR_LOGIN_REQUEST_COOLDOWN_SECONDS", "30"))


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
        raise HTTPException(
            status_code=422,
            detail="Use 3-32 lowercase letters, numbers, dots, dashes, or underscores",
        )
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
    forwarded_proto = request.headers.get(
        "x-forwarded-proto", request.url.scheme
    ).split(",", 1)[0].strip().lower()
    forwarded_host = request.headers.get(
        "x-forwarded-host", request.headers.get("host", request.url.netloc)
    ).split(",", 1)[0].strip().lower()
    hostname = forwarded_host.split(":", 1)[0]
    allowed_host = hostname == RP_ID or hostname.endswith(f".{RP_ID}")
    local_development = RP_ID in {"localhost", "127.0.0.1"} and hostname in {
        "localhost",
        "127.0.0.1",
    }
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
    log.warning(
        "Passkey registration rejected for RP %s; %s",
        RP_ID,
        " | ".join(failures),
    )
    raise HTTPException(
        status_code=400,
        detail="Device verification could not be confirmed. Try again.",
    )


def _verify_login(
    credential: dict,
    challenge: bytes,
    public_key: bytes,
    sign_count: int,
    request: Request,
):
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


def _username_exists_or_reserved(
    db: sqlite3.Connection,
    username: str,
    address: str,
) -> bool:
    return bool(
        db.execute("SELECT 1 FROM users WHERE email=?", (address,)).fetchone()
        or db.execute("SELECT 1 FROM mailboxes WHERE username=?", (username,)).fetchone()
        or db.execute("SELECT 1 FROM passkey_signups WHERE username=?", (username,)).fetchone()
    )


@router.post("/register/passkey/start", status_code=201)
def start_passkey_signup(body: PasskeyStartRequest) -> dict:
    username = _username(body.username)
    address = f"{username}@{MAIL_DOMAIN}"
    now = datetime.now(timezone.utc)
    user_handle = os.urandom(32)
    with _connect() as db:
        _prepare(db)
        db.execute("DELETE FROM passkey_signups WHERE expires_at<=?", (now.isoformat(),))
        if _username_exists_or_reserved(db, username, address):
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
        try:
            db.execute(
                """INSERT INTO passkey_signups(
                       username,name,address,password_hash,user_handle,challenge,
                       expires_at,created_at
                   ) VALUES (?,?,?,?,?,?,?,?)""",
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
        except sqlite3.IntegrityError as exc:
            db.rollback()
            raise HTTPException(
                status_code=409,
                detail="That Amosclaud username is already taken",
            ) from exc
    return {
        "address": address,
        "public_key": json.loads(options_to_json(options)),
        "expires_in_minutes": SETUP_MINUTES,
    }


@router.post("/register/passkey/finish", status_code=201)
def finish_passkey_signup(
    body: PasskeyFinishRequest,
    response: Response,
    request: Request,
) -> dict:
    username = _username(body.username)
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as db:
        _prepare(db)
        pending = db.execute(
            "SELECT * FROM passkey_signups WHERE username=?",
            (username,),
        ).fetchone()
        if not pending or pending["expires_at"] <= now:
            raise HTTPException(status_code=400, detail="Signup expired. Start again.")
        verified = _verify_registration(body.credential, bytes(pending["challenge"]), request)
        if (
            db.execute("SELECT 1 FROM users WHERE email=?", (pending["address"],)).fetchone()
            or db.execute("SELECT 1 FROM mailboxes WHERE username=?", (username,)).fetchone()
        ):
            raise HTTPException(status_code=409, detail="That Amosclaud username is already taken")
        first_user = db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
        try:
            cursor = db.execute(
                """INSERT INTO users(
                       name,email,password_hash,provider,is_admin,created_at
                   ) VALUES (?,?,?,'passkey',?,?)""",
                (
                    pending["name"],
                    pending["address"],
                    pending["password_hash"],
                    int(first_user),
                    now,
                ),
            )
            user_id = cursor.lastrowid
            db.execute(
                """INSERT INTO passkey_credentials(
                       credential_id,user_id,public_key,sign_count,created_at
                   ) VALUES (?,?,?,?,?)""",
                (
                    bytes_to_base64url(verified.credential_id),
                    user_id,
                    verified.credential_public_key,
                    verified.sign_count,
                    now,
                ),
            )
            db.execute(
                """INSERT INTO mailboxes(user_id,username,address,created_at)
                   VALUES (?,?,?,?)""",
                (user_id, username, pending["address"], now),
            )
            db.execute("DELETE FROM passkey_signups WHERE username=?", (username,))
            token = _create_session(db, user_id)
            user = db.execute(
                "SELECT id,name,email,is_admin,provider FROM users WHERE id=?",
                (user_id,),
            ).fetchone()
            db.commit()
        except sqlite3.IntegrityError as exc:
            db.rollback()
            raise HTTPException(
                status_code=409,
                detail="That Amosclaud username is already taken",
            ) from exc
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
        db.execute(
            "DELETE FROM passkey_login_challenges WHERE expires_at<=?",
            (now.isoformat(),),
        )
        db.execute(
            """INSERT INTO passkey_login_challenges(
                   attempt_hash,challenge,expires_at,created_at
               ) VALUES (?,?,?,?)""",
            (
                _token_hash(attempt),
                options.challenge,
                (now + timedelta(minutes=5)).isoformat(),
                now.isoformat(),
            ),
        )
        db.commit()
    return {"attempt": attempt, "public_key": json.loads(options_to_json(options))}


@router.post("/login/passkey/finish")
def finish_passkey_login(
    body: PasskeyLoginFinishRequest,
    response: Response,
    request: Request,
) -> dict:
    credential_id = str(body.credential.get("id") or "")
    if not credential_id:
        raise HTTPException(status_code=400, detail="Missing device credential")
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as db:
        _prepare(db)
        challenge_row = db.execute(
            """SELECT * FROM passkey_login_challenges
               WHERE attempt_hash=? AND expires_at>?""",
            (_token_hash(body.attempt), now),
        ).fetchone()
        if not challenge_row:
            raise HTTPException(status_code=400, detail="Fingerprint sign-in expired. Try again.")
        credential = db.execute(
            """SELECT passkey_credentials.*,users.id AS uid,users.name,users.email,
                      users.is_admin,users.provider
               FROM passkey_credentials
               JOIN users ON users.id=passkey_credentials.user_id
               WHERE passkey_credentials.credential_id=?""",
            (credential_id,),
        ).fetchone()
        if not credential:
            raise HTTPException(
                status_code=401,
                detail="This device is not linked to an Amosclaud account",
            )
        verified = _verify_login(
            body.credential,
            bytes(challenge_row["challenge"]),
            bytes(credential["public_key"]),
            int(credential["sign_count"]),
            request,
        )
        db.execute(
            "UPDATE passkey_credentials SET sign_count=? WHERE credential_id=?",
            (verified.new_sign_count, credential_id),
        )
        db.execute(
            "DELETE FROM passkey_login_challenges WHERE attempt_hash=?",
            (_token_hash(body.attempt),),
        )
        token = _create_session(db, credential["user_id"])
        user = db.execute(
            "SELECT id,name,email,is_admin,provider FROM users WHERE id=?",
            (credential["user_id"],),
        ).fetchone()
        db.commit()
    _set_session_cookie(response, token)
    return {"user": _user_response(user).model_dump()}


class QRLoginStartRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=32)


class QRDeviceStartRequest(BaseModel):
    challenge: str = Field(..., min_length=20, max_length=200)


class QRDeviceFinishRequest(BaseModel):
    challenge: str = Field(..., min_length=20, max_length=200)
    attempt: str = Field(..., min_length=20, max_length=200)
    credential: dict


class QRLoginVerifyRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=32)
    challenge: str = Field(..., min_length=20, max_length=200)
    browser_token: str = Field(..., min_length=20, max_length=200)
    code: str = Field(..., min_length=6, max_length=6, pattern=r"^[0-9]{6}$")


def _prepare_qr(db: sqlite3.Connection) -> None:
    _prepare(db)
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS qr_login_challenges (
            challenge_hash TEXT PRIMARY KEY,
            username TEXT NOT NULL COLLATE NOCASE,
            user_id INTEGER,
            browser_token_hash TEXT NOT NULL,
            webauthn_attempt_hash TEXT,
            webauthn_challenge BLOB,
            code_hash TEXT,
            code_expires_at TEXT,
            failed_attempts INTEGER NOT NULL DEFAULT 0,
            approved_at TEXT,
            used_at TEXT,
            expires_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_qr_login_username_created
        ON qr_login_challenges(username, created_at);
        """
    )
    db.commit()


def _public_origin(request: Request) -> str:
    configured = os.getenv("AMOSCLAUD_PUBLIC_URL", "https://www.amosclaud.com").strip()
    if configured:
        return configured.rstrip("/")
    forwarded_proto = request.headers.get("x-forwarded-proto", request.url.scheme).split(",", 1)[0]
    forwarded_host = request.headers.get(
        "x-forwarded-host", request.headers.get("host", "")
    ).split(",", 1)[0]
    if forwarded_proto.strip().lower() != "https" or not forwarded_host.strip():
        raise HTTPException(status_code=503, detail="Secure QR login requires HTTPS")
    return f"https://{forwarded_host.strip()}"


def _scan_url(request: Request, challenge: str) -> str:
    return (
        f"{_public_origin(request)}/api/v1/auth/login/qr/device"
        f"?challenge={quote(challenge, safe='')}"
    )


def _active_row(db: sqlite3.Connection, challenge: str) -> sqlite3.Row | None:
    return db.execute(
        """SELECT * FROM qr_login_challenges
           WHERE challenge_hash=? AND used_at IS NULL""",
        (_token_hash(challenge),),
    ).fetchone()


def _clean_expired(db: sqlite3.Connection, now: datetime) -> None:
    cutoff = (now - timedelta(days=1)).isoformat()
    db.execute(
        "DELETE FROM qr_login_challenges WHERE created_at<? OR used_at IS NOT NULL",
        (cutoff,),
    )


@router.post("/login/qr/start", status_code=201)
def start_qr_login(body: QRLoginStartRequest, request: Request) -> dict[str, object]:
    username = _username(body.username)
    address = f"{username}@{MAIL_DOMAIN}"
    now = datetime.now(timezone.utc)
    challenge = secrets.token_urlsafe(32)
    browser_token = secrets.token_urlsafe(32)

    with _connect() as db:
        _prepare_qr(db)
        _clean_expired(db, now)
        recent = db.execute(
            """SELECT created_at FROM qr_login_challenges
               WHERE username=? ORDER BY created_at DESC LIMIT 1""",
            (username,),
        ).fetchone()
        if recent:
            created_at = datetime.fromisoformat(str(recent["created_at"]))
            if (now - created_at).total_seconds() < QR_REQUEST_COOLDOWN_SECONDS:
                raise HTTPException(
                    status_code=429,
                    detail="Wait a moment before requesting another QR code",
                )

        user = db.execute(
            """SELECT users.id
               FROM users
               LEFT JOIN mailboxes ON mailboxes.user_id=users.id
               WHERE mailboxes.username=? OR users.email=?
               ORDER BY CASE WHEN mailboxes.username=? THEN 0 ELSE 1 END
               LIMIT 1""",
            (username, address, username),
        ).fetchone()
        user_id = int(user["id"]) if user else None
        db.execute(
            """INSERT INTO qr_login_challenges(
                   challenge_hash,username,user_id,browser_token_hash,expires_at,created_at
               ) VALUES (?,?,?,?,?,?)""",
            (
                _token_hash(challenge),
                username,
                user_id,
                _token_hash(browser_token),
                (now + timedelta(seconds=QR_CHALLENGE_SECONDS)).isoformat(),
                now.isoformat(),
            ),
        )
        db.commit()

    return {
        "challenge": challenge,
        "browser_token": browser_token,
        "qr_image_url": f"/api/v1/auth/login/qr/image?challenge={quote(challenge, safe='')}",
        "expires_in_seconds": QR_CHALLENGE_SECONDS,
        "message": "Scan the QR code with a trusted Amosclaud device.",
    }


@router.get("/login/qr/image", include_in_schema=False)
def qr_login_image(challenge: str, request: Request) -> Response:
    with _connect() as db:
        _prepare_qr(db)
        row = _active_row(db, challenge)
        now = datetime.now(timezone.utc).isoformat()
        if not row or (not row["approved_at"] and row["expires_at"] <= now):
            raise HTTPException(status_code=404, detail="QR login request expired")

    image = qrcode.make(_scan_url(request, challenge), image_factory=SvgPathImage)
    output = io.BytesIO()
    image.save(output)
    return Response(
        output.getvalue(),
        media_type="image/svg+xml",
        headers={
            "Cache-Control": "no-store, max-age=0",
            "Content-Security-Policy": "default-src 'none'",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/login/qr/device", include_in_schema=False)
def qr_device_page() -> FileResponse:
    return FileResponse(
        WEB_DIR / "qr-device.html",
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@router.post("/login/qr/device/start")
def start_qr_device_approval(body: QRDeviceStartRequest) -> dict[str, object]:
    now = datetime.now(timezone.utc)
    with _connect() as db:
        _prepare_qr(db)
        row = _active_row(db, body.challenge)
        if (
            not row
            or row["expires_at"] <= now.isoformat()
            or row["user_id"] is None
            or row["approved_at"] is not None
        ):
            raise HTTPException(
                status_code=400,
                detail="This QR login request is invalid or expired",
            )
        credential_count = db.execute(
            "SELECT COUNT(*) FROM passkey_credentials WHERE user_id=?",
            (row["user_id"],),
        ).fetchone()[0]
        if not credential_count:
            raise HTTPException(
                status_code=400,
                detail="This account has no trusted device. Use the password instead.",
            )

        attempt = secrets.token_urlsafe(32)
        options = generate_authentication_options(
            rp_id=RP_ID,
            user_verification=UserVerificationRequirement.REQUIRED,
        )
        db.execute(
            """UPDATE qr_login_challenges
               SET webauthn_attempt_hash=?,webauthn_challenge=?
               WHERE challenge_hash=?""",
            (_token_hash(attempt), options.challenge, _token_hash(body.challenge)),
        )
        db.commit()

    return {
        "attempt": attempt,
        "username": str(row["username"]),
        "public_key": json.loads(options_to_json(options)),
    }


@router.post("/login/qr/device/finish")
def finish_qr_device_approval(
    body: QRDeviceFinishRequest,
    request: Request,
) -> dict[str, object]:
    credential_id = str(body.credential.get("id") or "")
    if not credential_id:
        raise HTTPException(status_code=400, detail="Missing device credential")
    now = datetime.now(timezone.utc)

    with _connect() as db:
        _prepare_qr(db)
        row = _active_row(db, body.challenge)
        if (
            not row
            or row["expires_at"] <= now.isoformat()
            or row["user_id"] is None
            or row["approved_at"] is not None
            or not row["webauthn_attempt_hash"]
            or not row["webauthn_challenge"]
            or not secrets.compare_digest(
                str(row["webauthn_attempt_hash"]),
                _token_hash(body.attempt),
            )
        ):
            raise HTTPException(
                status_code=400,
                detail="This QR login request is invalid or expired",
            )

        credential = db.execute(
            """SELECT * FROM passkey_credentials
               WHERE credential_id=? AND user_id=?""",
            (credential_id, row["user_id"]),
        ).fetchone()
        if not credential:
            raise HTTPException(
                status_code=401,
                detail="This trusted device does not belong to the requested username",
            )

        verified = _verify_login(
            body.credential,
            bytes(row["webauthn_challenge"]),
            bytes(credential["public_key"]),
            int(credential["sign_count"]),
            request,
        )
        code = f"{secrets.randbelow(1_000_000):06d}"
        code_expires = now + timedelta(seconds=QR_CODE_SECONDS)
        db.execute(
            "UPDATE passkey_credentials SET sign_count=? WHERE credential_id=?",
            (verified.new_sign_count, credential_id),
        )
        db.execute(
            """UPDATE qr_login_challenges
               SET code_hash=?,code_expires_at=?,approved_at=?,
                   webauthn_attempt_hash=NULL,webauthn_challenge=NULL
               WHERE challenge_hash=?""",
            (
                _token_hash(code),
                code_expires.isoformat(),
                now.isoformat(),
                _token_hash(body.challenge),
            ),
        )
        db.commit()

    return {
        "username": str(row["username"]),
        "code": code,
        "expires_in_seconds": QR_CODE_SECONDS,
        "message": "Enter this one-time code on the browser that displayed the QR code.",
    }


@router.post("/login/qr/verify")
def verify_qr_login(body: QRLoginVerifyRequest, response: Response) -> dict[str, object]:
    username = _username(body.username)
    now = datetime.now(timezone.utc)

    with _connect() as db:
        _prepare_qr(db)
        row = _active_row(db, body.challenge)
        valid_request = bool(
            row
            and secrets.compare_digest(str(row["username"]), username)
            and secrets.compare_digest(
                str(row["browser_token_hash"]),
                _token_hash(body.browser_token),
            )
            and row["user_id"] is not None
            and row["approved_at"] is not None
            and row["code_hash"] is not None
            and row["code_expires_at"] is not None
            and str(row["code_expires_at"]) > now.isoformat()
            and int(row["failed_attempts"]) < QR_MAX_ATTEMPTS
        )
        code_matches = bool(
            valid_request
            and secrets.compare_digest(str(row["code_hash"]), _token_hash(body.code))
        )
        if not code_matches:
            if row:
                db.execute(
                    """UPDATE qr_login_challenges
                       SET failed_attempts=failed_attempts+1
                       WHERE challenge_hash=?""",
                    (_token_hash(body.challenge),),
                )
                db.commit()
            raise HTTPException(status_code=400, detail="Invalid or expired QR sign-in code")

        db.execute(
            """UPDATE qr_login_challenges
               SET used_at=?,code_hash=NULL
               WHERE challenge_hash=?""",
            (now.isoformat(), _token_hash(body.challenge)),
        )
        token = _create_session(db, int(row["user_id"]))
        user = db.execute(
            "SELECT id,name,email,is_admin,provider FROM users WHERE id=?",
            (row["user_id"],),
        ).fetchone()
        db.commit()

    _set_session_cookie(response, token)
    return {"user": _user_response(user).model_dump()}

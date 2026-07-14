"""Amosclaud-native authentication with email verification and optional GitHub linking."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import smtplib
import sqlite3
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Cookie, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from amoscloud_ai.admin_bootstrap import should_grant_admin

router = APIRouter(prefix="/auth", tags=["auth"])

DB_PATH = Path(os.getenv("AUTH_DB_PATH", "data/auth.db"))
SESSION_COOKIE = "amos_session"
OAUTH_STATE_COOKIE = "amos_oauth_state"
SESSION_DAYS = int(os.getenv("AUTH_SESSION_DAYS", "7"))
CODE_MINUTES = int(os.getenv("AUTH_CODE_MINUTES", "15"))
PBKDF2_ROUNDS = 310_000


class RegisterCodeRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    email: str = Field(..., min_length=5, max_length=254)
    password: str = Field(..., min_length=10, max_length=200)


class RegisterVerifyRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=254)
    password: str = Field(..., min_length=10, max_length=200)
    code: str = Field(..., min_length=6, max_length=6)


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=254)
    password: str = Field(..., min_length=1, max_length=200)


class EmailRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=254)


class PasswordResetRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=254)
    password: str = Field(..., min_length=10, max_length=200)
    code: str = Field(..., min_length=6, max_length=6)


class UserResponse(BaseModel):
    id: int
    name: str
    email: str
    is_admin: bool
    provider: str


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE COLLATE NOCASE,
            password_hash TEXT,
            github_id TEXT UNIQUE,
            provider TEXT NOT NULL DEFAULT 'password',
            is_admin INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token_hash TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            expires_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS auth_codes (
            email TEXT NOT NULL,
            purpose TEXT NOT NULL CHECK(purpose IN ('register','reset')),
            code_hash TEXT NOT NULL,
            name TEXT,
            password_hash TEXT,
            expires_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY(email, purpose)
        );
        """
    )
    db.commit()
    return db


def _normalise_email(email: str) -> str:
    value = email.strip().lower()
    if "@" not in value or value.startswith("@") or value.endswith("@"):
        raise HTTPException(status_code=422, detail="Enter a valid email address")
    return value


def _hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${PBKDF2_ROUNDS}${salt.hex()}${digest.hex()}"


def _verify_password(password: str, encoded: str | None) -> bool:
    if not encoded:
        return False
    try:
        algorithm, rounds, salt_hex, expected_hex = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(rounds))
        return hmac.compare_digest(actual, bytes.fromhex(expected_hex))
    except (ValueError, TypeError):
        return False


def _token_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_DAYS * 86400,
        httponly=True,
        secure=os.getenv("AUTH_COOKIE_SECURE", "true").lower() == "true",
        samesite="lax",
        path="/",
    )


def _create_session(db: sqlite3.Connection, user_id: int) -> str:
    token = secrets.token_urlsafe(48)
    now = datetime.now(timezone.utc)
    db.execute(
        "INSERT INTO sessions(token_hash,user_id,expires_at,created_at) VALUES (?,?,?,?)",
        (_token_hash(token), user_id, (now + timedelta(days=SESSION_DAYS)).isoformat(), now.isoformat()),
    )
    db.commit()
    return token


def get_user_from_session(token: str | None) -> sqlite3.Row | None:
    if not token:
        return None
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as db:
        db.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
        user = db.execute(
            """SELECT users.id,users.name,users.email,users.is_admin,users.provider
               FROM sessions JOIN users ON users.id=sessions.user_id
               WHERE sessions.token_hash=? AND sessions.expires_at>?""",
            (_token_hash(token), now),
        ).fetchone()
        db.commit()
        return user


def _user_response(row: sqlite3.Row) -> UserResponse:
    return UserResponse(id=row["id"], name=row["name"], email=row["email"], is_admin=bool(row["is_admin"]), provider=row["provider"])


def _send_code(email: str, code: str, purpose: str) -> None:
    host = os.getenv("SMTP_HOST")
    sender = os.getenv("SMTP_FROM", "no-reply@amosclaud.com")
    if not host:
        raise HTTPException(status_code=503, detail="Amosclaud email delivery is not configured")
    port = int(os.getenv("SMTP_PORT", "587"))
    username = os.getenv("SMTP_USERNAME")
    password = os.getenv("SMTP_PASSWORD")
    use_tls = os.getenv("SMTP_TLS", "true").lower() == "true"

    subject = "Verify your Amosclaud account" if purpose == "register" else "Reset your Amosclaud password"
    action = "complete your Amosclaud signup" if purpose == "register" else "reset your Amosclaud password"
    message = EmailMessage()
    message["From"] = sender
    message["To"] = email
    message["Subject"] = subject
    message.set_content(f"Your Amosclaud code is {code}. Use it within {CODE_MINUTES} minutes to {action}. If you did not request this, ignore this email.")

    with smtplib.SMTP(host, port, timeout=20) as smtp:
        if use_tls:
            smtp.starttls()
        if username and password:
            smtp.login(username, password)
        smtp.send_message(message)


def _create_code(db: sqlite3.Connection, email: str, purpose: str, name: str | None = None, password_hash: str | None = None) -> None:
    code = f"{secrets.randbelow(1_000_000):06d}"
    now = datetime.now(timezone.utc)
    db.execute(
        """INSERT INTO auth_codes(email,purpose,code_hash,name,password_hash,expires_at,created_at)
           VALUES (?,?,?,?,?,?,?)
           ON CONFLICT(email,purpose) DO UPDATE SET code_hash=excluded.code_hash,name=excluded.name,
           password_hash=excluded.password_hash,expires_at=excluded.expires_at,created_at=excluded.created_at""",
        (email, purpose, _token_hash(code), name, password_hash, (now + timedelta(minutes=CODE_MINUTES)).isoformat(), now.isoformat()),
    )
    db.commit()
    _send_code(email, code, purpose)


def _consume_code(db: sqlite3.Connection, email: str, purpose: str, code: str) -> sqlite3.Row:
    row = db.execute("SELECT * FROM auth_codes WHERE email=? AND purpose=?", (email, purpose)).fetchone()
    now = datetime.now(timezone.utc).isoformat()
    if not row or row["expires_at"] <= now or not hmac.compare_digest(row["code_hash"], _token_hash(code)):
        raise HTTPException(status_code=400, detail="Invalid or expired verification code")
    db.execute("DELETE FROM auth_codes WHERE email=? AND purpose=?", (email, purpose))
    return row


@router.post("/register/request-code", status_code=202)
def request_registration_code(body: RegisterCodeRequest) -> dict:
    email = _normalise_email(body.email)
    with _connect() as db:
        if db.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
            raise HTTPException(status_code=409, detail="An account with this email already exists")
        _create_code(db, email, "register", body.name.strip(), _hash_password(body.password))
    return {"message": "Verification code sent by Amosclaud"}


@router.post("/register/verify", response_model=UserResponse, status_code=201)
def verify_registration(body: RegisterVerifyRequest, response: Response) -> UserResponse:
    email = _normalise_email(body.email)
    with _connect() as db:
        if db.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
            raise HTTPException(status_code=409, detail="An account with this email already exists")
        pending = _consume_code(db, email, "register", body.code)
        if not _verify_password(body.password, pending["password_hash"]):
            raise HTTPException(status_code=400, detail="Password does not match the signup request")
        is_first_user = db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
        is_admin = should_grant_admin(email, is_first_user=is_first_user)
        cursor = db.execute(
            "INSERT INTO users(name,email,password_hash,provider,is_admin,created_at) VALUES (?,?,?,'password',?,?)",
            (pending["name"], email, pending["password_hash"], int(is_admin), datetime.now(timezone.utc).isoformat()),
        )
        token = _create_session(db, cursor.lastrowid)
        user = db.execute("SELECT id,name,email,is_admin,provider FROM users WHERE id=?", (cursor.lastrowid,)).fetchone()
    _set_session_cookie(response, token)
    return _user_response(user)


@router.post("/login", response_model=UserResponse)
def login(body: LoginRequest, response: Response) -> UserResponse:
    email = _normalise_email(body.email)
    with _connect() as db:
        user = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if not user or not _verify_password(body.password, user["password_hash"]):
            raise HTTPException(status_code=401, detail="Invalid email or password")
        token = _create_session(db, user["id"])
    _set_session_cookie(response, token)
    return _user_response(user)


@router.post("/password/forgot", status_code=202)
def forgot_password(body: EmailRequest) -> dict:
    email = _normalise_email(body.email)
    with _connect() as db:
        user = db.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
        if user:
            _create_code(db, email, "reset")
    return {"message": "If the account exists, Amosclaud sent a reset code"}


@router.post("/password/reset", status_code=204, response_class=Response)
def reset_password(body: PasswordResetRequest) -> Response:
    email = _normalise_email(body.email)
    with _connect() as db:
        user = db.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
        if not user:
            raise HTTPException(status_code=400, detail="Invalid or expired verification code")
        _consume_code(db, email, "reset", body.code)
        db.execute("UPDATE users SET password_hash=?,provider='password' WHERE id=?", (_hash_password(body.password), user["id"]))
        db.execute("DELETE FROM sessions WHERE user_id=?", (user["id"],))
        db.commit()
    return Response(status_code=204)


@router.get("/me", response_model=UserResponse)
def me(amos_session: str | None = Cookie(default=None)) -> UserResponse:
    user = get_user_from_session(amos_session)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return _user_response(user)


@router.post("/logout", status_code=204, response_class=Response)
def logout(response: Response, amos_session: str | None = Cookie(default=None)) -> Response:
    if amos_session:
        with _connect() as db:
            db.execute("DELETE FROM sessions WHERE token_hash=?", (_token_hash(amos_session),))
            db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.status_code = 204
    return response


@router.get("/github/link")
def github_link(request: Request, amos_session: str | None = Cookie(default=None)) -> RedirectResponse:
    user = get_user_from_session(amos_session)
    if not user:
        raise HTTPException(status_code=401, detail="Sign in to Amosclaud before connecting GitHub")
    client_id = os.getenv("GITHUB_CLIENT_ID")
    if not client_id:
        raise HTTPException(status_code=503, detail="GitHub integration is not configured")
    state = secrets.token_urlsafe(32)
    callback = os.getenv("GITHUB_CALLBACK_URL") or str(request.url_for("github_link_callback"))
    url = "https://github.com/login/oauth/authorize?" + urlencode({"client_id": client_id, "redirect_uri": callback, "scope": "read:user user:email repo", "state": state})
    response = RedirectResponse(url)
    response.set_cookie(OAUTH_STATE_COOKIE, state, max_age=600, httponly=True, secure=os.getenv("AUTH_COOKIE_SECURE", "true").lower() == "true", samesite="lax")
    return response


@router.get("/github/callback", name="github_link_callback")
async def github_link_callback(code: str, state: str, request: Request, amos_oauth_state: str | None = Cookie(default=None), amos_session: str | None = Cookie(default=None)) -> RedirectResponse:
    user = get_user_from_session(amos_session)
    if not user:
        raise HTTPException(status_code=401, detail="Sign in to Amosclaud before connecting GitHub")
    if not amos_oauth_state or not hmac.compare_digest(state, amos_oauth_state):
        raise HTTPException(status_code=400, detail="Invalid OAuth state")
    client_id = os.getenv("GITHUB_CLIENT_ID")
    client_secret = os.getenv("GITHUB_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise HTTPException(status_code=503, detail="GitHub integration is not configured")
    callback = os.getenv("GITHUB_CALLBACK_URL") or str(request.url_for("github_link_callback"))
    async with httpx.AsyncClient(timeout=15) as client:
        token_response = await client.post("https://github.com/login/oauth/access_token", headers={"Accept": "application/json"}, data={"client_id": client_id, "client_secret": client_secret, "code": code, "redirect_uri": callback})
        access_token = token_response.json().get("access_token")
        if not access_token:
            raise HTTPException(status_code=401, detail="GitHub connection failed")
        profile = (await client.get("https://api.github.com/user", headers={"Authorization": f"Bearer {access_token}", "Accept": "application/vnd.github+json"})).json()
    github_id = str(profile.get("id", ""))
    if not github_id:
        raise HTTPException(status_code=400, detail="GitHub account identifier is missing")
    with _connect() as db:
        conflict = db.execute("SELECT id FROM users WHERE github_id=? AND id!=?", (github_id, user["id"])).fetchone()
        if conflict:
            raise HTTPException(status_code=409, detail="This GitHub account is already linked to another Amosclaud user")
        db.execute("UPDATE users SET github_id=?,provider='password+github' WHERE id=?", (github_id, user["id"]))
        db.commit()
    response = RedirectResponse("/repositories?github=connected")
    response.delete_cookie(OAUTH_STATE_COOKIE)
    return response


@router.get("/github")
def github_login_disabled() -> None:
    raise HTTPException(status_code=410, detail="Sign in to Amosclaud first, then connect GitHub from repository settings")

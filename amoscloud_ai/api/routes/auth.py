"""Authentication API with Google OAuth as the active account provider."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Cookie, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

router = APIRouter(prefix="/auth", tags=["auth"])

DB_PATH = Path(os.getenv("AUTH_DB_PATH", "data/auth.db"))
SESSION_COOKIE = "amos_session"
OAUTH_STATE_COOKIE = "amos_oauth_state"
SESSION_DAYS = int(os.getenv("AUTH_SESSION_DAYS", "7"))
PBKDF2_ROUNDS = 310_000


class RegisterRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    email: str = Field(..., min_length=5, max_length=254)
    password: str = Field(..., min_length=10, max_length=200)


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=254)
    password: str = Field(..., min_length=1, max_length=200)


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
            google_id TEXT UNIQUE,
            provider TEXT NOT NULL DEFAULT 'google',
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
        """
    )
    columns = {row["name"] for row in db.execute("PRAGMA table_info(users)").fetchall()}
    if "google_id" not in columns:
        db.execute("ALTER TABLE users ADD COLUMN google_id TEXT")
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_google_id ON users(google_id)")
    db.commit()
    return db


def _normalise_email(email: str) -> str:
    value = email.strip().lower()
    if "@" not in value or value.startswith("@") or value.endswith("@"):
        raise HTTPException(status_code=422, detail="Enter a valid email address")
    return value


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


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


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
        "INSERT INTO sessions(token_hash, user_id, expires_at, created_at) VALUES (?, ?, ?, ?)",
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
            """SELECT users.id, users.name, users.email, users.is_admin, users.provider
               FROM sessions JOIN users ON users.id = sessions.user_id
               WHERE sessions.token_hash = ? AND sessions.expires_at > ?""",
            (_token_hash(token), now),
        ).fetchone()
        db.commit()
        return user


def _user_response(row: sqlite3.Row) -> UserResponse:
    return UserResponse(
        id=row["id"],
        name=row["name"],
        email=row["email"],
        is_admin=bool(row["is_admin"]),
        provider=row["provider"],
    )


@router.post("/register", status_code=410)
def register_disabled(body: RegisterRequest) -> None:
    raise HTTPException(status_code=410, detail="Account creation is available through Google only")


@router.post("/login", response_model=UserResponse)
def legacy_password_login(body: LoginRequest, response: Response) -> UserResponse:
    """Keep existing password accounts usable, while new accounts are Google-only."""
    email = _normalise_email(body.email)
    with _connect() as db:
        user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if not user or not _verify_password(body.password, user["password_hash"]):
            raise HTTPException(status_code=401, detail="Invalid email or password")
        token = _create_session(db, user["id"])
    _set_session_cookie(response, token)
    return _user_response(user)


@router.get("/me", response_model=UserResponse)
def me(amos_session: str | None = Cookie(default=None)) -> UserResponse:
    user = get_user_from_session(amos_session)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return _user_response(user)


@router.post("/logout", status_code=204)
def logout(response: Response, amos_session: str | None = Cookie(default=None)) -> Response:
    if amos_session:
        with _connect() as db:
            db.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(amos_session),))
            db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.status_code = 204
    return response


@router.get("/google")
def google_login(request: Request) -> RedirectResponse:
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    if not client_id:
        raise HTTPException(status_code=503, detail="Google sign-in is not configured")
    state = secrets.token_urlsafe(32)
    callback = os.getenv("GOOGLE_CALLBACK_URL") or str(request.url_for("google_callback"))
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(
        {
            "client_id": client_id,
            "redirect_uri": callback,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "access_type": "online",
            "prompt": "select_account",
        }
    )
    response = RedirectResponse(url)
    response.set_cookie(
        OAUTH_STATE_COOKIE,
        state,
        max_age=600,
        httponly=True,
        secure=os.getenv("AUTH_COOKIE_SECURE", "true").lower() == "true",
        samesite="lax",
    )
    return response


@router.get("/google/callback", name="google_callback")
async def google_callback(
    code: str,
    state: str,
    request: Request,
    amos_oauth_state: str | None = Cookie(default=None),
) -> RedirectResponse:
    if not amos_oauth_state or not hmac.compare_digest(state, amos_oauth_state):
        raise HTTPException(status_code=400, detail="Invalid OAuth state")

    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise HTTPException(status_code=503, detail="Google sign-in is not configured")

    callback = os.getenv("GOOGLE_CALLBACK_URL") or str(request.url_for("google_callback"))
    async with httpx.AsyncClient(timeout=20) as client:
        token_response = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": callback,
            },
        )
        if token_response.status_code >= 400:
            raise HTTPException(status_code=401, detail="Google authentication failed")
        access_token = token_response.json().get("access_token")
        if not access_token:
            raise HTTPException(status_code=401, detail="Google authentication failed")
        profile_response = await client.get(
            "https://openidconnect.googleapis.com/v1/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if profile_response.status_code >= 400:
            raise HTTPException(status_code=401, detail="Google profile could not be verified")
        profile = profile_response.json()

    if not profile.get("email_verified"):
        raise HTTPException(status_code=400, detail="Google account email must be verified")

    email = _normalise_email(profile.get("email", ""))
    google_id = str(profile.get("sub", ""))
    if not google_id:
        raise HTTPException(status_code=400, detail="Google account identifier is missing")
    name = (profile.get("name") or email.split("@", 1)[0]).strip()

    with _connect() as db:
        user = db.execute("SELECT * FROM users WHERE google_id = ? OR email = ?", (google_id, email)).fetchone()
        if user:
            db.execute(
                "UPDATE users SET google_id = ?, name = ?, provider = 'google' WHERE id = ?",
                (google_id, name, user["id"]),
            )
            user_id = user["id"]
        else:
            first_user = db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
            cursor = db.execute(
                """INSERT INTO users(name, email, google_id, provider, is_admin, created_at)
                   VALUES (?, ?, ?, 'google', ?, ?)""",
                (name, email, google_id, int(first_user), datetime.now(timezone.utc).isoformat()),
            )
            user_id = cursor.lastrowid
        token = _create_session(db, user_id)

    response = RedirectResponse("/")
    response.delete_cookie(OAUTH_STATE_COOKIE)
    _set_session_cookie(response, token)
    return response


@router.get("/github")
def github_disabled() -> None:
    raise HTTPException(status_code=410, detail="GitHub account sign-in is disabled. Continue with Google.")


@router.get("/github/callback")
def github_callback_disabled() -> None:
    raise HTTPException(status_code=410, detail="GitHub account sign-in is disabled. Continue with Google.")

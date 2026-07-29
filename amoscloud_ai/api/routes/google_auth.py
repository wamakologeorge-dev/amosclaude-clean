"""Google OpenID Connect sign-in with just-in-time Amosclaud provisioning."""

from __future__ import annotations

import hmac
import os
import secrets
import sqlite3
from datetime import datetime, timezone
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Cookie, HTTPException, Request
from fastapi.responses import RedirectResponse

from amoscloud_ai.admin_bootstrap import should_grant_admin
from amoscloud_ai.api.routes.auth import (
    _connect,
    _cookie_secure,
    _create_session,
    _normalise_email,
    _set_session_cookie,
)

router = APIRouter(prefix="/auth", tags=["auth"])

GOOGLE_STATE_COOKIE = "amos_google_oauth_state"
GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
GOOGLE_SCOPES = "openid email profile"


def _google_client_id() -> str:
    return os.getenv("GOOGLE_CLIENT_ID", "").strip()


def _google_client_secret() -> str:
    return os.getenv("GOOGLE_CLIENT_SECRET", "").strip()


def _configured() -> bool:
    return bool(_google_client_id() and _google_client_secret())


def _callback_url(request: Request) -> str:
    configured = os.getenv("GOOGLE_CALLBACK_URL", "").strip()
    if configured:
        return configured
    return str(request.url_for("google_oauth_callback"))


def _ensure_identity_table(db: sqlite3.Connection) -> None:
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS oauth_identities (
            provider TEXT NOT NULL,
            subject TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            email TEXT NOT NULL COLLATE NOCASE,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(provider, subject),
            UNIQUE(provider, email),
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """
    )
    db.commit()


def _merge_provider(current: str | None, provider: str) -> str:
    providers = [item for item in (current or "").split("+") if item]
    if provider not in providers:
        providers.append(provider)
    return "+".join(providers) or provider


def _provision_google_user(
    db: sqlite3.Connection,
    *,
    subject: str,
    email: str,
    name: str,
) -> sqlite3.Row:
    """Find, link, or create exactly one Amosclaud account for Google identity."""

    _ensure_identity_table(db)
    existing_identity = db.execute(
        """
        SELECT users.*
        FROM oauth_identities
        JOIN users ON users.id = oauth_identities.user_id
        WHERE oauth_identities.provider='google' AND oauth_identities.subject=?
        """,
        (subject,),
    ).fetchone()
    now = datetime.now(timezone.utc).isoformat()

    if existing_identity:
        email_owner = db.execute(
            "SELECT id FROM users WHERE email=? AND id!=?",
            (email, existing_identity["id"]),
        ).fetchone()
        if email_owner:
            raise HTTPException(
                status_code=409,
                detail="This Google email belongs to another Amosclaud account",
            )
        db.execute(
            """
            UPDATE oauth_identities
            SET email=?, updated_at=?
            WHERE provider='google' AND subject=?
            """,
            (email, now, subject),
        )
        db.commit()
        return db.execute(
            "SELECT * FROM users WHERE id=?", (existing_identity["id"],)
        ).fetchone()

    email_identity = db.execute(
        """
        SELECT user_id, subject
        FROM oauth_identities
        WHERE provider='google' AND email=?
        """,
        (email,),
    ).fetchone()
    if email_identity and email_identity["subject"] != subject:
        raise HTTPException(
            status_code=409,
            detail="This Google email is already linked to another identity",
        )

    user = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    if user is None:
        is_first_user = db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
        is_admin = should_grant_admin(email, is_first_user=is_first_user)
        cursor = db.execute(
            """
            INSERT INTO users(name,email,password_hash,provider,is_admin,created_at)
            VALUES (?,?,NULL,'google',?,?,?)
            """.replace(",?,?,?)", ",?,?)"),
            (name, email, int(is_admin), now),
        )
        user_id = int(cursor.lastrowid)
    else:
        user_id = int(user["id"])
        db.execute(
            "UPDATE users SET provider=? WHERE id=?",
            (_merge_provider(user["provider"], "google"), user_id),
        )

    db.execute(
        """
        INSERT INTO oauth_identities(provider,subject,user_id,email,created_at,updated_at)
        VALUES ('google',?,?,?,?,?)
        """,
        (subject, user_id, email, now, now),
    )
    db.commit()
    return db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()


def _login_error(code: str) -> RedirectResponse:
    response = RedirectResponse(f"/login?google_error={code}", status_code=302)
    response.delete_cookie(GOOGLE_STATE_COOKIE, path="/")
    return response


@router.get("/google/status")
def google_status(request: Request) -> dict[str, object]:
    """Tell the login page whether the server-side Google flow is configured."""

    return {
        "enabled": _configured(),
        "callback_url": _callback_url(request) if _configured() else None,
    }


@router.get("/google")
def google_login(request: Request) -> RedirectResponse:
    """Start a server-side OAuth authorization-code flow."""

    if not _configured():
        raise HTTPException(status_code=503, detail="Google sign-in is not configured")

    state = secrets.token_urlsafe(32)
    authorization_url = GOOGLE_AUTHORIZE_URL + "?" + urlencode(
        {
            "client_id": _google_client_id(),
            "redirect_uri": _callback_url(request),
            "response_type": "code",
            "scope": GOOGLE_SCOPES,
            "state": state,
            "prompt": "select_account",
            "include_granted_scopes": "true",
        }
    )
    response = RedirectResponse(authorization_url, status_code=302)
    response.set_cookie(
        GOOGLE_STATE_COOKIE,
        state,
        max_age=600,
        httponly=True,
        secure=_cookie_secure(),
        samesite="lax",
        path="/",
    )
    return response


@router.get("/google/callback", name="google_oauth_callback")
async def google_oauth_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    amos_google_oauth_state: str | None = Cookie(default=None),
) -> RedirectResponse:
    """Exchange Google's code, provision the account, and issue Amosclaud session."""

    if error:
        return _login_error("access_denied")
    if not code or not state:
        return _login_error("missing_response")
    if not amos_google_oauth_state or not hmac.compare_digest(
        state, amos_google_oauth_state
    ):
        raise HTTPException(status_code=400, detail="Invalid Google OAuth state")
    if not _configured():
        return _login_error("not_configured")

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            token_response = await client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "client_id": _google_client_id(),
                    "client_secret": _google_client_secret(),
                    "code": code,
                    "redirect_uri": _callback_url(request),
                    "grant_type": "authorization_code",
                },
                headers={"Accept": "application/json"},
            )
            token_response.raise_for_status()
            access_token = str(token_response.json().get("access_token") or "")
            if not access_token:
                return _login_error("token_exchange_failed")

            userinfo_response = await client.get(
                GOOGLE_USERINFO_URL,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/json",
                },
            )
            userinfo_response.raise_for_status()
            profile = userinfo_response.json()
    except (httpx.HTTPError, ValueError, TypeError):
        return _login_error("provider_unavailable")

    subject = str(profile.get("sub") or "").strip()
    raw_email = str(profile.get("email") or "").strip()
    verified = profile.get("email_verified") is True or str(
        profile.get("email_verified")
    ).lower() == "true"
    if not subject or not raw_email or not verified:
        return _login_error("unverified_email")

    email = _normalise_email(raw_email)
    name = str(profile.get("name") or email.split("@", 1)[0]).strip()[:100]
    if len(name) < 2:
        name = "Google user"

    try:
        with _connect() as db:
            user = _provision_google_user(
                db,
                subject=subject,
                email=email,
                name=name,
            )
            token = _create_session(db, int(user["id"]))
    except HTTPException as exc:
        if exc.status_code == 409:
            return _login_error("account_conflict")
        raise

    response = RedirectResponse("/cloud/agent?auth=google", status_code=302)
    _set_session_cookie(response, token)
    response.delete_cookie(GOOGLE_STATE_COOKIE, path="/")
    return response

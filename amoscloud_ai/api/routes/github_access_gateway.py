"""GitHub-only public account access for the Amosclaud production gateway."""

from __future__ import annotations

import hmac
import os
import secrets
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Cookie, HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from amoscloud_ai.admin_bootstrap import should_grant_admin
from amoscloud_ai.api.routes import auth

router = APIRouter(tags=["github-access"])

GITHUB_STATE_COOKIE = "amos_github_oauth_state"
GITHUB_RETURN_COOKIE = "amos_github_return_to"
GITHUB_SCOPE = "read:user user:email repo"


def _public_url() -> str:
    return os.getenv("AMOSCLAUD_PUBLIC_URL", "https://www.amosclaud.com").strip().rstrip("/")


def _callback_url() -> str:
    configured = os.getenv("GITHUB_CALLBACK_URL", "").strip()
    return configured or f"{_public_url()}/auth/github/callback"


def _safe_return_to(value: str | None) -> str:
    candidate = (value or "/cloud/agent").strip()
    if not candidate.startswith("/") or candidate.startswith("//"):
        return "/cloud/agent"
    return candidate


def _set_oauth_cookie(response: Response, name: str, value: str) -> None:
    response.set_cookie(
        name,
        value,
        max_age=600,
        httponly=True,
        secure=auth._cookie_secure(),
        samesite="lax",
        path="/",
        domain=auth._cookie_domain(),
    )


def _delete_oauth_cookies(response: Response) -> None:
    for name in (GITHUB_STATE_COOKIE, GITHUB_RETURN_COOKIE):
        response.delete_cookie(name, path="/", domain=auth._cookie_domain())


def _github_configuration() -> tuple[str, str]:
    client_id = os.getenv("GITHUB_CLIENT_ID", "").strip()
    client_secret = os.getenv("GITHUB_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise HTTPException(status_code=503, detail="GitHub account access is not configured")
    return client_id, client_secret


@router.get("/login", include_in_schema=False)
@router.get("/signup", include_in_schema=False)
@router.get("/create-account", include_in_schema=False)
def github_only_entry(request: Request) -> RedirectResponse:
    """Remove the password page and send every public account entry to GitHub."""

    if auth.get_user_from_session(request.cookies.get(auth.SESSION_COOKIE)):
        return RedirectResponse("/cloud/agent", status_code=302)
    return RedirectResponse("/auth/github", status_code=302)


@router.get("/auth/github", name="github_account_access")
def github_account_access(
    request: Request,
    return_to: str | None = None,
) -> RedirectResponse:
    """Start GitHub OAuth for both first-time signup and returning-user login."""

    if auth.get_user_from_session(request.cookies.get(auth.SESSION_COOKIE)):
        return RedirectResponse(_safe_return_to(return_to), status_code=302)

    client_id, _ = _github_configuration()
    state = secrets.token_urlsafe(32)
    authorization_url = "https://github.com/login/oauth/authorize?" + urlencode(
        {
            "client_id": client_id,
            "redirect_uri": _callback_url(),
            "scope": GITHUB_SCOPE,
            "state": state,
            "allow_signup": "true",
        }
    )
    response = RedirectResponse(authorization_url, status_code=302)
    _set_oauth_cookie(response, GITHUB_STATE_COOKIE, state)
    _set_oauth_cookie(response, GITHUB_RETURN_COOKIE, _safe_return_to(return_to))
    return response


def _verified_email(profile: dict[str, Any], emails: list[dict[str, Any]]) -> str | None:
    verified = [item for item in emails if item.get("verified") and item.get("email")]
    primary = next((item for item in verified if item.get("primary")), None)
    selected = primary or (verified[0] if verified else None)
    if selected:
        return auth._normalise_email(str(selected["email"]))

    profile_email = str(profile.get("email") or "").strip()
    if profile_email:
        return auth._normalise_email(profile_email)
    return None


async def _github_identity(code: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    client_id, client_secret = _github_configuration()
    async with httpx.AsyncClient(timeout=20) as client:
        token_response = await client.post(
            "https://github.com/login/oauth/access_token",
            headers={"Accept": "application/json"},
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "redirect_uri": _callback_url(),
            },
        )
        token_payload = token_response.json()
        access_token = str(token_payload.get("access_token") or "").strip()
        if not access_token:
            raise HTTPException(status_code=401, detail="GitHub account authorization failed")

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        profile_response = await client.get("https://api.github.com/user", headers=headers)
        if profile_response.status_code != 200:
            raise HTTPException(status_code=401, detail="GitHub account profile could not be verified")
        profile = profile_response.json()

        emails_response = await client.get("https://api.github.com/user/emails", headers=headers)
        emails = emails_response.json() if emails_response.status_code == 200 else []
        if not isinstance(emails, list):
            emails = []
    return profile, emails


def _find_or_create_github_user(
    profile: dict[str, Any],
    emails: list[dict[str, Any]],
) -> tuple[int, bool]:
    github_id = str(profile.get("id") or "").strip()
    github_login = str(profile.get("login") or "").strip()
    if not github_id or not github_login:
        raise HTTPException(status_code=400, detail="GitHub account identity is incomplete")

    verified_email = _verified_email(profile, emails)
    account_email = verified_email or f"github-{github_id}@users.noreply.amosclaud.local"
    display_name = str(profile.get("name") or github_login).strip() or github_login

    with auth._connect() as db:
        user = db.execute("SELECT * FROM users WHERE github_id=?", (github_id,)).fetchone()
        created = False

        if not user and verified_email:
            user = db.execute("SELECT * FROM users WHERE email=?", (verified_email,)).fetchone()
            if user:
                db.execute(
                    "UPDATE users SET github_id=?,provider='github' WHERE id=?",
                    (github_id, user["id"]),
                )

        if not user:
            is_first_user = db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
            is_admin = should_grant_admin(account_email, is_first_user=is_first_user)
            cursor = db.execute(
                """INSERT INTO users(
                       name,email,password_hash,github_id,provider,is_admin,created_at
                   ) VALUES (?,?,NULL,?,'github',?,?)""",
                (
                    display_name,
                    account_email,
                    github_id,
                    int(is_admin),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            user_id = int(cursor.lastrowid)
            created = True
        else:
            user_id = int(user["id"])
            db.execute(
                """UPDATE users SET
                       name=CASE WHEN name='' THEN ? ELSE name END,
                       github_id=?,provider='github'
                   WHERE id=?""",
                (display_name, github_id, user_id),
            )

        token = auth._create_session(db, user_id)
    return user_id, created, token


@router.get("/auth/github/callback", name="github_account_callback")
async def github_account_callback(
    code: str,
    state: str,
    amos_github_oauth_state: str | None = Cookie(default=None),
    amos_github_return_to: str | None = Cookie(default=None),
) -> RedirectResponse:
    """Create or sign in any verified GitHub user and issue an Amosclaud session."""

    if not amos_github_oauth_state or not hmac.compare_digest(state, amos_github_oauth_state):
        raise HTTPException(status_code=400, detail="Invalid GitHub OAuth state")

    profile, emails = await _github_identity(code)
    _, created, token = _find_or_create_github_user(profile, emails)
    destination = _safe_return_to(amos_github_return_to)
    separator = "&" if "?" in destination else "?"
    response = RedirectResponse(
        f"{destination}{separator}github={'created' if created else 'signed-in'}",
        status_code=302,
    )
    auth._set_session_cookie(response, token)
    _delete_oauth_cookies(response)
    return response


def _github_required() -> None:
    raise HTTPException(
        status_code=410,
        detail={
            "code": "github_account_required",
            "message": "Email and password access has been removed. Continue with GitHub.",
            "authorization_url": "/auth/github",
        },
    )


@router.post("/auth/register/request-code")
@router.post("/auth/register/verify")
@router.post("/auth/login")
@router.post("/auth/login/request-code")
@router.post("/auth/login/verify-code")
@router.post("/auth/password/forgot")
@router.post("/auth/password/reset")
def disabled_email_account_access() -> None:
    """Prevent old clients from silently restoring password or email-code access."""

    _github_required()


__all__ = [
    "router",
    "github_account_access",
    "github_account_callback",
    "disabled_email_account_access",
]

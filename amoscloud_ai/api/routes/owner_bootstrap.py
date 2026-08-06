"""Secure platform-owner bootstrap and GitHub-only root access."""

from __future__ import annotations

import hmac
import os
import secrets
from datetime import datetime, timezone
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Cookie, HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from amoscloud_ai.admin_bootstrap import (
    configured_admin_emails,
    configured_admin_github_email,
    configured_admin_github_repository,
    is_configured_github_admin,
)
from amoscloud_ai.api.routes import auth

router = APIRouter(prefix="/auth", tags=["auth"])
GITHUB_ADMIN_STATE_COOKIE = "amos_github_admin_state"


def _github_admin_callback_url(request: Request) -> str:
    return os.getenv("GITHUB_ADMIN_CALLBACK_URL") or str(request.url_for("github_admin_callback"))


def _send_github_redirect_uri() -> bool:
    return os.getenv("GITHUB_ADMIN_SEND_REDIRECT_URI", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _shared_cookie_domain() -> str | None:
    return os.getenv("AUTH_COOKIE_DOMAIN", "").strip() or None


def _github_headers(access_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _github_admin_email(
    profile: dict[str, object],
    verified_emails: list[dict[str, object]],
) -> str:
    for email in verified_emails:
        if email.get("primary") and email.get("verified") and email.get("email"):
            return str(email["email"]).strip().lower()
    profile_email = str(profile.get("email") or "").strip().lower()
    return profile_email or configured_admin_github_email()


def _reject_github_only_email_access(email: str) -> None:
    with auth._connect() as db:
        user = db.execute(
            "SELECT provider FROM users WHERE email=?",
            (email,),
        ).fetchone()
    if user and user["provider"] == "github-admin":
        raise HTTPException(
            status_code=403,
            detail=(
                "This platform-owner account is GitHub-only. "
                "Use Continue with GitHub on the Amosclaud sign-in page."
            ),
        )


@router.post("/register/request-code", status_code=202)
def request_registration_or_bootstrap(
    body: auth.RegisterCodeRequest,
    response: Response,
) -> dict[str, object]:
    """Send a verification code, or securely create the first configured owner.

    Normal public registration still requires email verification. The fallback is
    available only when SMTP is absent, the user database is empty, and the email
    is explicitly listed in AMOSCLAUD_ADMIN_EMAILS.
    """
    if os.getenv("SMTP_HOST", "").strip():
        return auth.request_registration_code(body)

    email = auth._normalise_email(body.email)
    if email not in configured_admin_emails():
        raise HTTPException(
            status_code=503,
            detail=(
                "Email delivery is not configured. The platform owner must add this "
                "email to AMOSCLAUD_ADMIN_EMAILS or configure SMTP before registration."
            ),
        )

    with auth._connect() as db:
        if db.execute("SELECT COUNT(*) FROM users").fetchone()[0] != 0:
            raise HTTPException(
                status_code=503,
                detail="Email delivery must be configured before creating additional accounts.",
            )
        if db.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
            raise HTTPException(status_code=409, detail="An account with this email already exists")

        cursor = db.execute(
            "INSERT INTO users(name,email,password_hash,provider,is_admin,created_at) "
            "VALUES (?,?,?,'password',1,?)",
            (
                body.name.strip(),
                email,
                auth._hash_password(body.password),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        token = auth._create_session(db, cursor.lastrowid)

    auth._set_session_cookie(response, token)
    return {
        "message": "Owner account created. Opening Amosclaud…",
        "account_created": True,
    }


@router.post("/login", response_model=auth.UserResponse)
def protected_password_login(
    body: auth.LoginRequest,
    response: Response,
) -> auth.UserResponse:
    email = auth._normalise_email(body.email)
    _reject_github_only_email_access(email)
    return auth.login(body, response)


@router.post("/login/request-code", status_code=202)
def protected_login_code_request(body: auth.EmailRequest) -> dict[str, str]:
    email = auth._normalise_email(body.email)
    with auth._connect() as db:
        user = db.execute(
            "SELECT provider FROM users WHERE email=?",
            (email,),
        ).fetchone()
    if user and user["provider"] == "github-admin":
        return {"message": "If the account exists, Amosclaud sent a sign-in code"}
    return auth.request_login_code(body)


@router.post("/login/verify-code", response_model=auth.UserResponse)
def protected_login_code_verify(
    body: auth.EmailCodeLoginRequest,
    response: Response,
) -> auth.UserResponse:
    email = auth._normalise_email(body.email)
    _reject_github_only_email_access(email)
    return auth.verify_login_code(body, response)


@router.post("/password/forgot", status_code=202)
def protected_password_forgot(body: auth.EmailRequest) -> dict[str, str]:
    email = auth._normalise_email(body.email)
    with auth._connect() as db:
        user = db.execute(
            "SELECT provider FROM users WHERE email=?",
            (email,),
        ).fetchone()
    if user and user["provider"] == "github-admin":
        return {"message": "If the account exists, Amosclaud sent a reset code"}
    return auth.forgot_password(body)


@router.post("/password/reset", status_code=204, response_class=Response)
def protected_password_reset(body: auth.PasswordResetRequest) -> Response:
    email = auth._normalise_email(body.email)
    _reject_github_only_email_access(email)
    return auth.reset_password(body)


@router.get("/github/admin-login", name="github_admin_login")
def github_admin_login(request: Request) -> RedirectResponse:
    """Start GitHub OAuth for the configured platform owner.

    Amosclaud never receives or stores the GitHub password. GitHub authenticates
    the owner and returns a short-lived authorization code.
    """
    client_id = os.getenv("GITHUB_CLIENT_ID")
    if not client_id:
        raise HTTPException(
            status_code=503,
            detail="GitHub owner sign-in is not configured",
        )
    state = secrets.token_urlsafe(32)
    callback = _github_admin_callback_url(request)
    authorize_parameters = {
        "client_id": client_id,
        "scope": "read:user user:email repo",
        "state": state,
        "allow_signup": "false",
    }
    if _send_github_redirect_uri():
        authorize_parameters["redirect_uri"] = callback
    authorize_url = "https://github.com/login/oauth/authorize?" + urlencode(authorize_parameters)
    response = RedirectResponse(authorize_url)
    response.set_cookie(
        GITHUB_ADMIN_STATE_COOKIE,
        state,
        max_age=600,
        httponly=True,
        secure=auth._cookie_secure(),
        samesite="lax",
        path="/",
        domain=_shared_cookie_domain(),
    )
    return response


@router.get("/github/admin-callback", name="github_admin_callback")
async def github_admin_callback(
    code: str,
    state: str,
    request: Request,
    amos_github_admin_state: str | None = Cookie(default=None),
) -> RedirectResponse:
    """Create a passwordless root session for the verified repository owner."""
    if not amos_github_admin_state or not hmac.compare_digest(
        state,
        amos_github_admin_state,
    ):
        raise HTTPException(status_code=400, detail="Invalid GitHub OAuth state")

    client_id = os.getenv("GITHUB_CLIENT_ID")
    client_secret = os.getenv("GITHUB_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise HTTPException(
            status_code=503,
            detail="GitHub owner sign-in is not configured",
        )

    callback = _github_admin_callback_url(request)
    token_parameters = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
    }
    if _send_github_redirect_uri():
        token_parameters["redirect_uri"] = callback
    async with httpx.AsyncClient(timeout=20) as client:
        token_response = await client.post(
            "https://github.com/login/oauth/access_token",
            headers={"Accept": "application/json"},
            data=token_parameters,
        )
        token_payload = token_response.json()
        access_token = token_payload.get("access_token")
        if not access_token:
            raise HTTPException(status_code=401, detail="GitHub authentication failed")

        headers = _github_headers(str(access_token))
        profile_response = await client.get(
            "https://api.github.com/user",
            headers=headers,
        )
        profile = profile_response.json()
        github_id = str(profile.get("id") or "")
        login = str(profile.get("login") or "").strip()
        if (
            not github_id
            or not login
            or not is_configured_github_admin(
                github_id,
                login,
            )
        ):
            raise HTTPException(
                status_code=403,
                detail="This GitHub account is not the configured Amosclaud owner",
            )

        repository_name = configured_admin_github_repository()
        repository_response = await client.get(
            f"https://api.github.com/repos/{repository_name}",
            headers=headers,
        )
        repository = repository_response.json()
        permissions = repository.get("permissions") or {}
        owner = repository.get("owner") or {}
        owns_repository = (
            repository_response.status_code == 200
            and str(repository.get("full_name") or "").lower() == repository_name.lower()
            and str(owner.get("login") or "").lower() == login.lower()
            and permissions.get("admin") is True
        )
        if not owns_repository:
            raise HTTPException(
                status_code=403,
                detail=(
                    "GitHub verified the account, but it does not currently own "
                    "and administer the configured Amosclaud repository"
                ),
            )

        emails_response = await client.get(
            "https://api.github.com/user/emails",
            headers=headers,
        )
        verified_emails = (
            emails_response.json()
            if emails_response.status_code == 200 and isinstance(emails_response.json(), list)
            else []
        )

    email = _github_admin_email(profile, verified_emails)
    now = datetime.now(timezone.utc).isoformat()
    with auth._connect() as db:
        by_github = db.execute(
            "SELECT * FROM users WHERE github_id=?",
            (github_id,),
        ).fetchone()
        by_email = db.execute(
            "SELECT * FROM users WHERE email=?",
            (email,),
        ).fetchone()
        if by_github and by_email and by_github["id"] != by_email["id"]:
            raise HTTPException(
                status_code=409,
                detail="The verified GitHub identity conflicts with another Amosclaud account",
            )
        user = by_github or by_email
        if user:
            user_id = int(user["id"])
            db.execute(
                """UPDATE users
                   SET name=?,email=?,password_hash=NULL,github_id=?,
                       provider='github-admin',is_admin=1
                   WHERE id=?""",
                (login, email, github_id, user_id),
            )
        else:
            cursor = db.execute(
                """INSERT INTO users(
                       name,email,password_hash,github_id,provider,is_admin,created_at
                   ) VALUES (?,?,NULL,?,'github-admin',1,?)""",
                (login, email, github_id, now),
            )
            user_id = int(cursor.lastrowid)

        # Root access is GitHub-only. End any older password or email-code
        # sessions before issuing the newly verified owner session.
        db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        token = auth._create_session(db, user_id)

    response = RedirectResponse("/admin?github=owner", status_code=302)
    auth._set_session_cookie(response, token)
    response.delete_cookie(GITHUB_ADMIN_STATE_COOKIE, path="/", domain=_shared_cookie_domain())
    return response

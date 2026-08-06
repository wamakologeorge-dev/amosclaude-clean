"""Production owner access in front of the normal Amosclaud account routes.

Normal registration always attempts verified email first. When delivery returns a
503, only the configured owner email may create the first account, and only while
the account database is empty. GitHub owner verification remains available as a
passwordless recovery path.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Cookie, HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from amoscloud_ai.admin_bootstrap import configured_admin_emails
from amoscloud_ai.api.routes import auth, owner_bootstrap

router = APIRouter(prefix="/auth", tags=["owner-access"])


def _create_first_configured_owner(
    body: auth.RegisterCodeRequest,
    response: Response,
    delivery_error: HTTPException,
) -> dict[str, object]:
    email = auth._normalise_email(body.email)
    if email not in configured_admin_emails():
        raise delivery_error

    with auth._connect() as db:
        if db.execute("SELECT COUNT(*) FROM users").fetchone()[0] != 0:
            raise delivery_error
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
        token = auth._create_session(db, int(cursor.lastrowid))

    auth._set_session_cookie(response, token)
    return {
        "message": "Owner account created securely. Opening Amosclaud…",
        "account_created": True,
    }


@router.post("/register/request-code", status_code=202)
def request_registration_or_owner_bootstrap(
    body: auth.RegisterCodeRequest,
    response: Response,
) -> dict[str, object]:
    """Use verified email, with a first-owner fallback only after delivery failure."""

    try:
        return auth.request_registration_code(body)
    except HTTPException as exc:
        if exc.status_code != 503:
            raise
        return _create_first_configured_owner(body, response, exc)


@router.get("/github/admin-login", name="github_admin_login")
def github_admin_login(request: Request) -> RedirectResponse:
    """Start GitHub verification for the configured Amosclaud platform owner."""

    return owner_bootstrap.github_admin_login(request)


@router.get("/github/admin-callback", name="github_admin_callback")
async def github_admin_callback(
    code: str,
    state: str,
    request: Request,
    amos_github_admin_state: str | None = Cookie(default=None),
) -> RedirectResponse:
    """Finish the existing state-protected GitHub owner login flow."""

    return await owner_bootstrap.github_admin_callback(
        code,
        state,
        request,
        amos_github_admin_state,
    )


__all__ = ["router", "request_registration_or_owner_bootstrap"]

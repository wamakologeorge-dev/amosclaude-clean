"""Secure first-owner account bootstrap when outbound email is not configured."""

from __future__ import annotations

import os
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Response

from amoscloud_ai.admin_bootstrap import configured_admin_emails
from amoscloud_ai.api.routes import auth

router = APIRouter(prefix="/auth", tags=["auth"])


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

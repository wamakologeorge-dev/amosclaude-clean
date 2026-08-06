"""Optional, identity-verified recovery routes for the configured platform owner.

Normal visitors use the public email account routes. Email-delivery failures do
not create accounts or grant administrator access. The configured owner may use
the separate GitHub verification flow as a recovery option.
"""

from __future__ import annotations

from fastapi import APIRouter, Cookie, Request
from fastapi.responses import RedirectResponse

from amoscloud_ai.api.routes import owner_bootstrap

router = APIRouter(prefix="/auth", tags=["owner-access"])


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
    """Finish the existing state-protected GitHub owner recovery flow."""

    return await owner_bootstrap.github_admin_callback(
        code,
        state,
        request,
        amos_github_admin_state,
    )


__all__ = ["router"]

"""Production Amosclaud application with platform-owner recovery routes.

Railway historically started ``amoscloud_ai.main:app``. The platform-owner
GitHub recovery gateway is intentionally kept outside the public account router,
so this entry point adds only those verified owner routes without changing the
rest of the deployed platform surface.

Both the root and ``/api/v1`` paths are registered because older production
settings used ``/api/v1/auth/github/admin-callback`` while the current owner
login page uses ``/auth/github/admin-login``.
"""

from __future__ import annotations

from amoscloud_ai.api.routes import owner_access_gateway
from amoscloud_ai.main import app


def _has_path(path: str) -> bool:
    return any(getattr(route, "path", None) == path for route in app.routes)


if not _has_path("/auth/github/admin-login"):
    app.include_router(owner_access_gateway.router)

if not _has_path("/api/v1/auth/github/admin-login"):
    app.include_router(owner_access_gateway.router, prefix="/api/v1")


__all__ = ["app"]

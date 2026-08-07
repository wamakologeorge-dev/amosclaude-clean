"""Production Amosclaud application with platform-owner recovery routes.

Railway historically started ``amoscloud_ai.main:app``.  The platform-owner
GitHub recovery gateway is intentionally kept outside the public account router,
so this entry point adds only those verified owner routes without changing the
rest of the deployed platform surface.
"""

from __future__ import annotations

from amoscloud_ai.api.routes import owner_access_gateway
from amoscloud_ai.main import app


def _route_key(route: object) -> tuple[str | None, tuple[str, ...]]:
    path = getattr(route, "path", None)
    methods = tuple(sorted(getattr(route, "methods", None) or ()))
    return path, methods


_existing_routes = {_route_key(route) for route in app.routes}
if not any(key[0] == "/auth/github/admin-login" for key in _existing_routes):
    app.include_router(owner_access_gateway.router)


__all__ = ["app"]

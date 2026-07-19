"""Framework-version-independent discovery of registered application routes."""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def route_paths(routes: Iterable[Any]) -> set[str]:
    """Return paths from direct routes and nested FastAPI/Starlette wrappers.

    FastAPI versions expose included routers differently: some place child routes
    in ``routes`` while others retain them behind ``router`` or ``app`` objects.
    Child route paths are already fully resolved, so discovery must traverse every
    supported container without prepending wrapper paths.
    """
    discovered: set[str] = set()
    pending = list(routes)
    seen: set[int] = set()

    while pending:
        route = pending.pop()
        identity = id(route)
        if identity in seen:
            continue
        seen.add(identity)

        path = getattr(route, "path", None)
        if isinstance(path, str):
            discovered.add(path)

        nested = getattr(route, "routes", None)
        if nested:
            pending.extend(nested)

        nested_router = getattr(route, "router", None)
        router_routes = getattr(nested_router, "routes", None)
        if router_routes:
            pending.extend(router_routes)

        nested_app = getattr(route, "app", None)
        app_routes = getattr(nested_app, "routes", None)
        if app_routes:
            pending.extend(app_routes)

    return discovered

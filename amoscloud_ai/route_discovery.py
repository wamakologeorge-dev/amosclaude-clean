"""Framework-version-independent discovery of registered application routes."""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def _join(prefix: str, path: str) -> str:
    if not prefix:
        return path or ""
    if not path:
        return prefix
    return f"{prefix.rstrip('/')}/{path.lstrip('/')}"


def route_paths(routes: Iterable[Any]) -> set[str]:
    """Return complete paths from direct and nested FastAPI/Starlette routes.

    Newer FastAPI versions may preserve included routers as wrapper routes. Their
    child paths are relative to the wrapper path, so route verification must carry
    the parent prefix while traversing nested ``routes``, ``router``, and ``app``
    objects.
    """
    discovered: set[str] = set()
    pending: list[tuple[Any, str]] = [(route, "") for route in routes]
    seen: set[tuple[int, str]] = set()

    while pending:
        route, prefix = pending.pop()
        marker = (id(route), prefix)
        if marker in seen:
            continue
        seen.add(marker)

        path = getattr(route, "path", "")
        full_path = _join(prefix, path) if isinstance(path, str) else prefix
        if full_path:
            discovered.add(full_path)

        children = getattr(route, "routes", None)
        if children:
            pending.extend((child, full_path) for child in children)

        nested_router = getattr(route, "router", None)
        router_routes = getattr(nested_router, "routes", None)
        if router_routes:
            pending.extend((child, full_path) for child in router_routes)

        nested_app = getattr(route, "app", None)
        app_routes = getattr(nested_app, "routes", None)
        if app_routes:
            pending.extend((child, full_path) for child in app_routes)

    return discovered

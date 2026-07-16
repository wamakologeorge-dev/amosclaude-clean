"""Framework-version-independent discovery of registered application routes."""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def route_paths(routes: Iterable[Any]) -> set[str]:
    """Return paths from direct routes and nested FastAPI router wrappers."""
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
    return discovered

"""Thread-safe byte route registration and dispatch."""

from __future__ import annotations

import inspect
import threading
from collections.abc import Awaitable, Callable
from typing import Any, TypeAlias

from .core import ByteFrame

RouteResult: TypeAlias = ByteFrame | bytes | str | dict[str, Any] | list[Any] | None
RouteHandler: TypeAlias = Callable[[ByteFrame], RouteResult | Awaitable[RouteResult]]


class RouteNotFound(LookupError):
    pass


class ByteRouter:
    def __init__(self) -> None:
        self._routes: dict[str, RouteHandler] = {}
        self._lock = threading.RLock()

    def route(self, name: str) -> Callable[[RouteHandler], RouteHandler]:
        def decorator(handler: RouteHandler) -> RouteHandler:
            self.register(name, handler)
            return handler

        return decorator

    def register(self, name: str, handler: RouteHandler, *, replace: bool = False) -> None:
        if not name or any(char.isspace() for char in name):
            raise ValueError("route name must be non-empty and whitespace-free")
        if not callable(handler):
            raise TypeError("route handler must be callable")
        with self._lock:
            if name in self._routes and not replace:
                raise ValueError(f"route already registered: {name}")
            self._routes[name] = handler

    def unregister(self, name: str) -> bool:
        with self._lock:
            return self._routes.pop(name, None) is not None

    def routes(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._routes))

    def _handler(self, route: str) -> RouteHandler:
        with self._lock:
            handler = self._routes.get(route) or self._routes.get("*")
        if handler is None:
            raise RouteNotFound(route)
        return handler

    @staticmethod
    def _normalize(frame: ByteFrame, result: RouteResult) -> ByteFrame:
        response_route = f"{frame.route}.result"
        if isinstance(result, ByteFrame):
            return result
        if isinstance(result, bytes):
            return ByteFrame(response_route, result, headers={"request-id": frame.frame_id})
        if isinstance(result, str):
            return ByteFrame.from_text(
                response_route,
                result,
                headers={"request-id": frame.frame_id},
            )
        if result is None:
            return ByteFrame(response_route, b"", headers={"request-id": frame.frame_id})
        return ByteFrame.from_json(
            response_route,
            result,
            headers={"request-id": frame.frame_id},
        )

    async def dispatch(self, frame: ByteFrame) -> ByteFrame:
        result = self._handler(frame.route)(frame)
        if inspect.isawaitable(result):
            result = await result
        return self._normalize(frame, result)

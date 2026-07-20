"""Managed runtime that connects byte routes, lifecycle state, and metrics."""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Any

from .core import ByteFrame
from .router import ByteRouter, RouteNotFound


class ByteSystem:
    def __init__(self, router: ByteRouter | None = None, *, name: str = "amosclaud-byte") -> None:
        self.router = router or ByteRouter()
        self.name = name
        self.started_ns: int | None = None
        self._requests = 0
        self._failures = 0
        self._lock = threading.Lock()
        self.router.register("system.ping", lambda _frame: {"status": "ok", "system": self.name})
        self.router.register("system.routes", lambda _frame: {"routes": self.router.routes()})

    @property
    def running(self) -> bool:
        return self.started_ns is not None

    def start(self) -> None:
        if self.started_ns is None:
            self.started_ns = time.time_ns()

    def stop(self) -> None:
        self.started_ns = None

    async def execute(self, frame: ByteFrame) -> ByteFrame:
        if not self.running:
            raise RuntimeError("byte system is not running")
        with self._lock:
            self._requests += 1
        try:
            return await self.router.dispatch(frame)
        except Exception:
            with self._lock:
                self._failures += 1
            raise

    def execute_sync(self, frame: ByteFrame) -> ByteFrame:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.execute(frame))
        raise RuntimeError("execute_sync cannot run inside an active event loop; await execute")

    def status(self) -> dict[str, Any]:
        uptime_ms = (time.time_ns() - self.started_ns) // 1_000_000 if self.started_ns else 0
        return {
            "name": self.name,
            "running": self.running,
            "uptime_ms": uptime_ms,
            "requests": self._requests,
            "failures": self._failures,
            "routes": self.router.routes(),
        }

    def safe_execute_sync(self, frame: ByteFrame) -> ByteFrame:
        try:
            return self.execute_sync(frame)
        except RouteNotFound as exc:
            return ByteFrame.from_json(
                f"{frame.route}.error",
                {"error": "route_not_found", "route": str(exc)},
            )

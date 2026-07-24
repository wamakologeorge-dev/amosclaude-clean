"""Deterministic task queue for the first OS milestone."""

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import RLock
from typing import Any
from uuid import uuid4


@dataclass
class ScheduledTask:
    operation: str
    payload: dict[str, Any]
    id: str = field(default_factory=lambda: str(uuid4()))
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class TaskScheduler:
    def __init__(self) -> None:
        self._queue: deque[ScheduledTask] = deque()
        self._lock = RLock()

    def submit(self, operation: str, payload: dict[str, Any]) -> ScheduledTask:
        task = ScheduledTask(operation=operation, payload=payload)
        with self._lock:
            self._queue.append(task)
        return task

    def next(self) -> ScheduledTask | None:
        with self._lock:
            return self._queue.popleft() if self._queue else None

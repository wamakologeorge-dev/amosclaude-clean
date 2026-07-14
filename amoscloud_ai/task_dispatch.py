"""Helpers for dispatching background tasks without blocking API replies."""

from __future__ import annotations

import socket
from urllib.parse import urlparse
from typing import Any

from amoscloud_ai.config import settings


DEFAULT_PORTS = {
    "amqp": 5672,
    "amqps": 5671,
    "redis": 6379,
    "rediss": 6379,
}


def _ensure_broker_reachable(timeout: float = 0.5) -> None:
    parsed = urlparse(settings.celery_broker_url)
    host = parsed.hostname
    port = parsed.port or DEFAULT_PORTS.get(parsed.scheme)

    if not host or not port:
        return

    with socket.create_connection((host, port), timeout=timeout):
        return


def dispatch_task(task: Any, *args: Any) -> None:
    _ensure_broker_reachable()
    task.apply_async(args=args, retry=False)

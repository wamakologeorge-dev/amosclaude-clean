"""Runtime service registry."""

from dataclasses import dataclass
from threading import RLock


@dataclass(frozen=True)
class ServiceDescriptor:
    name: str
    version: str
    status: str = "ready"


class ServiceRegistry:
    def __init__(self) -> None:
        self._services: dict[str, ServiceDescriptor] = {}
        self._lock = RLock()

    def register(self, descriptor: ServiceDescriptor) -> None:
        with self._lock:
            self._services[descriptor.name] = descriptor

    def list(self) -> list[ServiceDescriptor]:
        with self._lock:
            return list(self._services.values())

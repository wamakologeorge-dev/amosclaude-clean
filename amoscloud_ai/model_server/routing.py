"""Model-backend routing controlled by Amosclaud Autonomous."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


class ModelBackend(Protocol):
    name: str
    def health(self) -> dict[str, Any]: ...
    def generate(self, prompt: str, **options: Any) -> str: ...


@dataclass
class ModelRouter:
    backends: dict[str, ModelBackend] = field(default_factory=dict)
    mode_routes: dict[str, list[str]] = field(default_factory=dict)

    def register(self, backend: ModelBackend) -> None:
        name = backend.name.strip()
        if not name:
            raise ValueError("backend name cannot be empty")
        self.backends[name] = backend

    def configure_mode(self, mode: str, backend_names: list[str]) -> None:
        unknown = [name for name in backend_names if name not in self.backends]
        if unknown:
            raise KeyError(f"unknown model backends: {', '.join(unknown)}")
        self.mode_routes[mode] = list(backend_names)

    def choose(self, mode: str, preferred: str | None = None) -> ModelBackend:
        candidates = ([preferred] if preferred else []) + self.mode_routes.get(mode, []) + list(self.backends)
        visited: set[str] = set()
        for name in candidates:
            if not name or name in visited or name not in self.backends:
                continue
            visited.add(name)
            backend = self.backends[name]
            health = backend.health()
            if str(health.get("status", "")).lower() in {"ok", "ready", "healthy", "available"}:
                return backend
        raise RuntimeError(f"no healthy model backend is available for mode {mode!r}")

    def generate(self, mode: str, prompt: str, *, preferred: str | None = None, **options: Any) -> tuple[str, str]:
        backend = self.choose(mode, preferred)
        return backend.generate(prompt, **options), backend.name

"""Thread-safe provider registry."""

from __future__ import annotations

from threading import RLock

from .base import ModelProvider


class ProviderRegistry:
    """Register model providers once and expose deterministic snapshots."""

    def __init__(self) -> None:
        self._providers: dict[str, ModelProvider] = {}
        self._lock = RLock()

    def register(self, provider: ModelProvider, *, replace: bool = False) -> None:
        key = provider.key.strip().lower()
        if not key:
            raise ValueError("provider key cannot be empty")
        with self._lock:
            if key in self._providers and not replace:
                raise ValueError(f"provider '{key}' is already registered")
            self._providers[key] = provider

    def unregister(self, key: str) -> ModelProvider | None:
        with self._lock:
            return self._providers.pop(key.strip().lower(), None)

    def get(self, key: str) -> ModelProvider:
        normalized = key.strip().lower()
        with self._lock:
            try:
                return self._providers[normalized]
            except KeyError as exc:
                raise KeyError(f"provider '{normalized}' is not registered") from exc

    def providers(self) -> tuple[ModelProvider, ...]:
        with self._lock:
            return tuple(
                sorted(
                    self._providers.values(),
                    key=lambda provider: (-provider.priority, provider.key),
                )
            )

    def keys(self) -> tuple[str, ...]:
        return tuple(provider.key for provider in self.providers())

    def __len__(self) -> int:
        with self._lock:
            return len(self._providers)

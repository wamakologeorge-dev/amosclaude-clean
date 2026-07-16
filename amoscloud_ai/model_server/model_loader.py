"""Model lifecycle management without downloading assets implicitly."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any, Callable


@dataclass(frozen=True)
class ModelSpec:
    name: str
    provider: str
    model_path: str | None = None
    device: str = "cpu"
    dtype: str = "float32"


class ModelLoader:
    def __init__(self) -> None:
        self._factories: dict[str, Callable[[ModelSpec], Any]] = {}
        self._models: dict[str, Any] = {}
        self._specs: dict[str, ModelSpec] = {}
        self._lock = RLock()

    def register_provider(self, provider: str, factory: Callable[[ModelSpec], Any]) -> None:
        if not provider.strip():
            raise ValueError("provider cannot be empty")
        self._factories[provider] = factory

    def load(self, spec: ModelSpec, *, reload: bool = False) -> Any:
        with self._lock:
            if spec.name in self._models and not reload:
                return self._models[spec.name]
            if spec.provider not in self._factories:
                raise KeyError(f"no loader registered for provider {spec.provider!r}")
            if spec.model_path and not Path(spec.model_path).expanduser().exists():
                raise FileNotFoundError(f"configured model path does not exist: {spec.model_path}")
            model = self._factories[spec.provider](spec)
            self._models[spec.name] = model
            self._specs[spec.name] = spec
            return model

    def get(self, name: str) -> Any:
        with self._lock:
            if name not in self._models:
                raise KeyError(f"model {name!r} is not loaded")
            return self._models[name]

    def unload(self, name: str) -> None:
        with self._lock:
            model = self._models.pop(name, None)
            self._specs.pop(name, None)
            if model is not None and hasattr(model, "close"):
                model.close()

    def status(self) -> list[dict[str, str]]:
        with self._lock:
            return [
                {"name": name, "provider": self._specs[name].provider, "device": self._specs[name].device, "status": "loaded"}
                for name in sorted(self._models)
            ]

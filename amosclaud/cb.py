"""Core component-bundle primitives for Amosclaud."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class CBComponent:
    """One registered Amosclaud component-bundle capability."""

    name: str
    kind: str
    version: str = "1.0"
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CBRegistry:
    """Small deterministic registry used by CB packages and bundle manifests."""

    def __init__(self) -> None:
        self._components: dict[str, CBComponent] = {}
        self._handlers: dict[str, Callable[..., Any]] = {}

    def register(self, component: CBComponent, handler: Callable[..., Any] | None = None) -> CBComponent:
        if not component.name.strip():
            raise ValueError("component name is required")
        if component.name in self._components:
            raise ValueError(f"component already registered: {component.name}")
        self._components[component.name] = component
        if handler is not None:
            self._handlers[component.name] = handler
        return component

    def get(self, name: str) -> CBComponent:
        try:
            return self._components[name]
        except KeyError as exc:
            raise KeyError(f"unknown Amosclaud CB component: {name}") from exc

    def list(self) -> list[CBComponent]:
        return [self._components[name] for name in sorted(self._components)]

    def execute(self, name: str, **kwargs: Any) -> Any:
        handler = self._handlers.get(name)
        if handler is None:
            raise RuntimeError(f"component has no executable handler: {name}")
        return handler(**kwargs)


registry = CBRegistry()

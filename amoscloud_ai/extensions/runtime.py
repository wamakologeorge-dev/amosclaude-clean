"""Runtime bootstrap for built-in, drop-in, and entry-point plugins.

The existing application already imports the control-bus dashboard router. That
router acts as the stable extension host, so new modules placed in
``amoscloud_ai.plugins`` or installed through the ``amosclaud.plugins`` entry
point can contribute routes and tools without another edit to ``main.py``.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from typing import Any

from fastapi import APIRouter

from amoscloud_ai import feature_flags
from amoscloud_ai.extensions.registry import PluginRegistry
from amoscloud_ai.logger import log

REGISTRY: PluginRegistry | None = None


def _drop_in_candidates() -> list[tuple[Any, str]]:
    package = importlib.import_module("amoscloud_ai.plugins")
    candidates: list[tuple[Any, str]] = []
    for module_info in sorted(pkgutil.iter_modules(package.__path__), key=lambda item: item.name):
        if module_info.name.startswith("_"):
            continue
        module_name = f"amoscloud_ai.plugins.{module_info.name}"
        module = importlib.import_module(module_name)
        candidate = getattr(module, "create_plugin", None) or getattr(module, "plugin", None)
        if candidate is None:
            log.info("Skipping plugin module without create_plugin/plugin: %s", module_name)
            continue
        candidates.append((candidate, f"drop-in:{module_name}"))
    return candidates


def _materialize(candidate: Any) -> Any:
    if inspect.isclass(candidate):
        return candidate()
    if callable(candidate) and not hasattr(candidate, "manifest"):
        return candidate()
    return candidate


def bootstrap_registry(host_router: APIRouter) -> PluginRegistry:
    global REGISTRY
    if REGISTRY is not None:
        return REGISTRY

    registry = PluginRegistry()
    for candidate, source in _drop_in_candidates():
        try:
            registry.register_plugin(_materialize(candidate), source=source)
        except Exception:
            log.exception("Drop-in plugin failed before registration: %s", source)

    # Installed packages and explicit operator modules are discovered through the
    # registry's entry-point/env loader. Drop-in modules are already loaded above.
    registry.discover()

    flag_definitions = []
    for record in registry.records.values():
        if record.status != "registered":
            continue
        try:
            for plugin_router, prefix in record.contribution.routers:
                host_router.include_router(plugin_router, prefix=prefix)
            flag_definitions.extend(record.contribution.feature_definitions)
            registry._merge_named(
                registry.agent_tools,
                record.contribution.agent_tools,
                record.manifest.plugin_id,
            )
            registry._merge_named(
                registry.terminal_commands,
                record.contribution.terminal_commands,
                record.manifest.plugin_id,
            )
            registry._merge_named(
                registry.mcp_server_factories,
                record.contribution.mcp_server_factories,
                record.manifest.plugin_id,
            )
            registry._merge_named(
                registry.health_checks,
                record.contribution.health_checks,
                record.manifest.plugin_id,
            )
            record.status = "mounted"
        except Exception as exc:
            record.status = "failed"
            record.error = f"{type(exc).__name__}: {exc}"[:2_000]
            log.exception("Plugin mount failed: %s", record.manifest.plugin_id)

    if flag_definitions:
        feature_flags.register_definitions(flag_definitions)

    # Synchronous startup hooks can initialize schemas immediately. Async hooks
    # remain registered for a future native FastAPI lifespan bridge rather than
    # being executed incorrectly during module import.
    for record in registry.records.values():
        if record.status != "mounted":
            continue
        try:
            for hook in record.contribution.startup_hooks:
                result = hook(None)
                if inspect.isawaitable(result):
                    if inspect.iscoroutine(result):
                        result.close()
                    raise RuntimeError(
                        "Async startup hooks require the native plugin lifespan bridge"
                    )
            record.status = "started"
        except Exception as exc:
            record.status = "failed"
            record.error = f"{type(exc).__name__}: {exc}"[:2_000]
            log.exception("Plugin startup failed: %s", record.manifest.plugin_id)

    REGISTRY = registry
    return registry


def get_registry() -> PluginRegistry:
    if REGISTRY is None:
        raise RuntimeError("Plugin registry is not initialized")
    return REGISTRY

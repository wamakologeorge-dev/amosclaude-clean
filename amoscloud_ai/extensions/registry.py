"""Dynamic Amosclaud plugin registry.

Trusted packages can expose an ``amosclaud.plugins`` Python entry point. Local
operators can also opt into explicit modules through ``AMOSCLAUD_PLUGIN_MODULES``.
The core application calls this registry once; individual features register
routers, flags, agent tools, terminal commands, checks, and lifecycle hooks
without editing ``main.py``.
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import os
import re
from dataclasses import dataclass, field
from importlib import metadata
from typing import Any, Awaitable, Callable, Iterable, Protocol, runtime_checkable

from fastapi import APIRouter, FastAPI

from amoscloud_ai import feature_flags
from amoscloud_ai.logger import log

_PLUGIN_ID = re.compile(r"^[a-z][a-z0-9_.-]{2,119}$")
_ENTRY_POINT_GROUP = "amosclaud.plugins"

LifecycleHook = Callable[[FastAPI], Awaitable[None] | None]
HealthCheck = Callable[[], dict[str, Any]]
AgentTool = Callable[..., Any]
TerminalCommand = Callable[..., Any]


class PluginError(RuntimeError):
    pass


@dataclass(frozen=True)
class PluginManifest:
    plugin_id: str
    name: str
    version: str
    description: str = ""
    api_prefix: str | None = None
    required_flags: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()

    def normalized(self) -> "PluginManifest":
        plugin_id = self.plugin_id.strip().lower()
        if not _PLUGIN_ID.fullmatch(plugin_id):
            raise PluginError(f"Invalid plugin ID: {self.plugin_id!r}")
        prefix = self.api_prefix
        if prefix is not None:
            prefix = "/" + prefix.strip("/")
            if ".." in prefix or not prefix.startswith("/api/v1/plugins/"):
                raise PluginError(
                    "Plugin API prefixes must stay under /api/v1/plugins/<plugin-id>"
                )
        return PluginManifest(
            plugin_id=plugin_id,
            name=self.name.strip()[:160] or plugin_id,
            version=self.version.strip()[:80] or "0",
            description=self.description.strip()[:2_000],
            api_prefix=prefix,
            required_flags=tuple(feature_flags.validate_key(item) for item in self.required_flags),
            capabilities=tuple(sorted({str(item).strip() for item in self.capabilities if str(item).strip()})),
        )


@runtime_checkable
class AmosclaudPlugin(Protocol):
    manifest: PluginManifest

    def register(self, context: "PluginContext") -> None:
        ...


@dataclass
class PluginContribution:
    routers: list[tuple[APIRouter, str]] = field(default_factory=list)
    feature_definitions: list[feature_flags.FlagDefinition] = field(default_factory=list)
    agent_tools: dict[str, AgentTool] = field(default_factory=dict)
    terminal_commands: dict[str, TerminalCommand] = field(default_factory=dict)
    mcp_server_factories: dict[str, Callable[..., Any]] = field(default_factory=dict)
    health_checks: dict[str, HealthCheck] = field(default_factory=dict)
    startup_hooks: list[LifecycleHook] = field(default_factory=list)
    shutdown_hooks: list[LifecycleHook] = field(default_factory=list)


@dataclass
class PluginRecord:
    manifest: PluginManifest
    source: str
    status: str = "discovered"
    error: str | None = None
    contribution: PluginContribution = field(default_factory=PluginContribution)

    def as_dict(self) -> dict[str, Any]:
        return {
            "plugin_id": self.manifest.plugin_id,
            "name": self.manifest.name,
            "version": self.manifest.version,
            "description": self.manifest.description,
            "source": self.source,
            "status": self.status,
            "error": self.error,
            "required_flags": list(self.manifest.required_flags),
            "capabilities": list(self.manifest.capabilities),
            "contributions": {
                "routers": len(self.contribution.routers),
                "feature_flags": len(self.contribution.feature_definitions),
                "agent_tools": sorted(self.contribution.agent_tools),
                "terminal_commands": sorted(self.contribution.terminal_commands),
                "mcp_server_factories": sorted(self.contribution.mcp_server_factories),
                "health_checks": sorted(self.contribution.health_checks),
                "startup_hooks": len(self.contribution.startup_hooks),
                "shutdown_hooks": len(self.contribution.shutdown_hooks),
            },
        }


class PluginContext:
    """Restricted registration surface exposed to a single trusted plugin."""

    def __init__(self, record: PluginRecord) -> None:
        self.record = record

    @property
    def plugin_id(self) -> str:
        return self.record.manifest.plugin_id

    def add_router(self, router: APIRouter, *, prefix: str | None = None) -> None:
        api_prefix = prefix or self.record.manifest.api_prefix or f"/api/v1/plugins/{self.plugin_id}"
        normalized = "/" + api_prefix.strip("/")
        if ".." in normalized or not normalized.startswith("/api/v1/plugins/"):
            raise PluginError("Plugin routers must be mounted under /api/v1/plugins/")
        self.record.contribution.routers.append((router, normalized))

    def define_flag(self, definition: feature_flags.FlagDefinition) -> None:
        if definition.owner_plugin != self.plugin_id:
            definition = feature_flags.FlagDefinition(
                key=definition.key,
                name=definition.name,
                description=definition.description,
                default_enabled=definition.default_enabled,
                rollout_percentage=definition.rollout_percentage,
                required_tiers=definition.required_tiers,
                owner_plugin=self.plugin_id,
            )
        self.record.contribution.feature_definitions.append(definition)

    def add_agent_tool(self, name: str, function: AgentTool) -> None:
        self._add_named(self.record.contribution.agent_tools, name, function)

    def add_terminal_command(self, name: str, function: TerminalCommand) -> None:
        self._add_named(self.record.contribution.terminal_commands, name, function)

    def add_mcp_server_factory(self, name: str, factory: Callable[..., Any]) -> None:
        self._add_named(self.record.contribution.mcp_server_factories, name, factory)

    def add_health_check(self, name: str, check: HealthCheck) -> None:
        self._add_named(self.record.contribution.health_checks, name, check)

    def on_startup(self, hook: LifecycleHook) -> None:
        self.record.contribution.startup_hooks.append(hook)

    def on_shutdown(self, hook: LifecycleHook) -> None:
        self.record.contribution.shutdown_hooks.append(hook)

    def _add_named(self, target: dict[str, Any], name: str, value: Any) -> None:
        key = str(name or "").strip().lower()
        if not re.fullmatch(r"[a-z][a-z0-9_.-]{2,119}", key):
            raise PluginError(f"Invalid contribution name: {name!r}")
        if key in target:
            raise PluginError(f"Duplicate contribution name inside {self.plugin_id}: {key}")
        target[key] = value


class PluginRegistry:
    def __init__(self) -> None:
        self.records: dict[str, PluginRecord] = {}
        self.agent_tools: dict[str, tuple[str, AgentTool]] = {}
        self.terminal_commands: dict[str, tuple[str, TerminalCommand]] = {}
        self.mcp_server_factories: dict[str, tuple[str, Callable[..., Any]]] = {}
        self.health_checks: dict[str, tuple[str, HealthCheck]] = {}
        self._startup_complete = False

    def register_plugin(self, plugin: AmosclaudPlugin, *, source: str) -> PluginRecord:
        if not isinstance(plugin, AmosclaudPlugin):
            raise PluginError(f"Object from {source} does not implement AmosclaudPlugin")
        manifest = plugin.manifest.normalized()
        if manifest.plugin_id in self.records:
            raise PluginError(f"Duplicate plugin ID: {manifest.plugin_id}")
        record = PluginRecord(manifest=manifest, source=source)
        self.records[manifest.plugin_id] = record
        try:
            plugin.register(PluginContext(record))
            record.status = "registered"
            return record
        except Exception as exc:
            record.status = "failed"
            record.error = f"{type(exc).__name__}: {exc}"[:2_000]
            log.exception("Plugin registration failed: %s", manifest.plugin_id)
            return record

    def discover(self, builtins: Iterable[Any] = ()) -> None:
        for index, candidate in enumerate(builtins):
            self._load_candidate(candidate, source=f"builtin:{index}")

        if os.getenv("AMOSCLAUD_DISABLE_ENTRYPOINT_PLUGINS", "false").strip().lower() not in {
            "1",
            "true",
            "yes",
            "on",
        }:
            try:
                discovered = metadata.entry_points()
                points = discovered.select(group=_ENTRY_POINT_GROUP) if hasattr(discovered, "select") else discovered.get(_ENTRY_POINT_GROUP, [])
                for point in points:
                    try:
                        self._load_candidate(point.load(), source=f"entrypoint:{point.name}")
                    except Exception as exc:
                        log.exception("Unable to load plugin entry point %s", point.name)
                        self._record_load_failure(f"entrypoint.{point.name}", f"entrypoint:{point.name}", exc)
            except Exception:
                log.exception("Plugin entry-point discovery failed")

        modules = [item.strip() for item in os.getenv("AMOSCLAUD_PLUGIN_MODULES", "").split(",") if item.strip()]
        for module_name in modules:
            try:
                module = importlib.import_module(module_name)
                candidate = getattr(module, "create_plugin", None) or getattr(module, "plugin", None)
                if candidate is None:
                    raise PluginError("Module must export create_plugin or plugin")
                self._load_candidate(candidate, source=f"module:{module_name}")
            except Exception as exc:
                log.exception("Unable to load configured plugin module %s", module_name)
                safe_id = re.sub(r"[^a-z0-9_.-]", "-", module_name.lower())[:100] or "module-load-failure"
                self._record_load_failure(safe_id, f"module:{module_name}", exc)

    def _load_candidate(self, candidate: Any, *, source: str) -> None:
        instance = candidate
        if inspect.isclass(candidate):
            instance = candidate()
        elif callable(candidate) and not hasattr(candidate, "manifest"):
            instance = candidate()
        self.register_plugin(instance, source=source)

    def _record_load_failure(self, plugin_id: str, source: str, exc: Exception) -> None:
        safe = re.sub(r"[^a-z0-9_.-]", "-", plugin_id.lower()).strip("-.")
        if not _PLUGIN_ID.fullmatch(safe):
            safe = f"plugin-load-failure-{len(self.records) + 1}"
        if safe in self.records:
            safe = f"{safe}-{len(self.records) + 1}"
        manifest = PluginManifest(
            plugin_id=safe,
            name=safe,
            version="0",
            description="Plugin failed before registration.",
        )
        self.records[safe] = PluginRecord(
            manifest=manifest,
            source=source,
            status="failed",
            error=f"{type(exc).__name__}: {exc}"[:2_000],
        )

    def mount(self, app: FastAPI) -> None:
        flag_definitions: list[feature_flags.FlagDefinition] = []
        for record in self.records.values():
            if record.status != "registered":
                continue
            try:
                for router, prefix in record.contribution.routers:
                    app.include_router(router, prefix=prefix)
                flag_definitions.extend(record.contribution.feature_definitions)
                self._merge_named(self.agent_tools, record.contribution.agent_tools, record.manifest.plugin_id)
                self._merge_named(self.terminal_commands, record.contribution.terminal_commands, record.manifest.plugin_id)
                self._merge_named(self.mcp_server_factories, record.contribution.mcp_server_factories, record.manifest.plugin_id)
                self._merge_named(self.health_checks, record.contribution.health_checks, record.manifest.plugin_id)
                record.status = "mounted"
            except Exception as exc:
                record.status = "failed"
                record.error = f"{type(exc).__name__}: {exc}"[:2_000]
                log.exception("Plugin mount failed: %s", record.manifest.plugin_id)
        if flag_definitions:
            feature_flags.register_definitions(flag_definitions)
        app.state.plugin_registry = self

    def _merge_named(self, target: dict[str, tuple[str, Any]], values: dict[str, Any], plugin_id: str) -> None:
        for name, value in values.items():
            global_name = f"{plugin_id}.{name}"
            if global_name in target:
                raise PluginError(f"Duplicate global contribution: {global_name}")
            target[global_name] = (plugin_id, value)

    async def startup(self, app: FastAPI) -> None:
        if self._startup_complete:
            return
        for record in self.records.values():
            if record.status not in {"mounted", "started"}:
                continue
            try:
                for hook in record.contribution.startup_hooks:
                    result = hook(app)
                    if inspect.isawaitable(result):
                        await result
                record.status = "started"
            except Exception as exc:
                record.status = "failed"
                record.error = f"{type(exc).__name__}: {exc}"[:2_000]
                log.exception("Plugin startup failed: %s", record.manifest.plugin_id)
        self._startup_complete = True

    async def shutdown(self, app: FastAPI) -> None:
        for record in reversed(list(self.records.values())):
            if record.status != "started":
                continue
            try:
                for hook in reversed(record.contribution.shutdown_hooks):
                    result = hook(app)
                    if inspect.isawaitable(result):
                        await result
                record.status = "stopped"
            except Exception as exc:
                record.status = "failed"
                record.error = f"{type(exc).__name__}: {exc}"[:2_000]
                log.exception("Plugin shutdown failed: %s", record.manifest.plugin_id)
        self._startup_complete = False

    def list_plugins(self) -> list[dict[str, Any]]:
        return [record.as_dict() for record in sorted(self.records.values(), key=lambda item: item.manifest.plugin_id)]

    def run_health_checks(self) -> list[dict[str, Any]]:
        results = []
        for name, (plugin_id, check) in sorted(self.health_checks.items()):
            try:
                payload = check()
                results.append({"name": name, "plugin_id": plugin_id, "status": "ok", "result": payload})
            except Exception:
                log.exception("Plugin health check failed: %s (%s)", plugin_id, name)
                results.append(
                    {
                        "name": name,
                        "plugin_id": plugin_id,
                        "status": "failed",
                        "error": "Health check failed",
                    }
                )
        return results


_registry_lock = asyncio.Lock()


def build_registry() -> PluginRegistry:
    from amoscloud_ai.plugins.control_plane import create_plugin

    registry = PluginRegistry()
    registry.discover(builtins=(create_plugin,))
    return registry

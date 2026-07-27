"""Built-in modular control-plane plugin.

This feature is loaded through ``amosclaud.plugins`` infrastructure just like an
external package. The primary application does not import its routers directly.
"""

from __future__ import annotations

from amoscloud_ai import feature_flags, mcp_manager
from amoscloud_ai.api.routes import extensions
from amoscloud_ai.extensions import PluginContext, PluginManifest


class ControlPlanePlugin:
    manifest = PluginManifest(
        plugin_id="control-plane",
        name="Plugin, MCP, and Feature Flag Control Plane",
        version="1.0.0",
        description=(
            "Dynamic extension discovery, scoped MCP servers, and deterministic "
            "user/workspace/tier feature rollouts."
        ),
        api_prefix="/api/v1/plugins/control-plane",
        capabilities=(
            "plugin-registry",
            "mcp-client-manager",
            "feature-flags",
        ),
    )

    def register(self, context: PluginContext) -> None:
        context.add_router(extensions.router)
        context.define_flag(
            feature_flags.FlagDefinition(
                key="mcp.integrations",
                name="MCP integrations",
                description="Expose assigned Model Context Protocol servers to agents and workspaces.",
                default_enabled=False,
                rollout_percentage=0,
                owner_plugin=context.plugin_id,
            )
        )
        context.define_flag(
            feature_flags.FlagDefinition(
                key="extensions.third_party",
                name="Third-party plugins",
                description="Allow installed Python entry-point extensions to contribute capabilities.",
                default_enabled=False,
                rollout_percentage=0,
                required_tiers=("full",),
                owner_plugin=context.plugin_id,
            )
        )
        context.define_flag(
            feature_flags.FlagDefinition(
                key="workspace.live_collaboration",
                name="Live multiplayer editing",
                description="Experimental real-time collaborative workspace editing.",
                default_enabled=False,
                rollout_percentage=0,
                owner_plugin=context.plugin_id,
            )
        )
        context.define_flag(
            feature_flags.FlagDefinition(
                key="ai.model_switching",
                name="Advanced AI model switching",
                description="Allow selected users to choose among approved model runtimes.",
                default_enabled=False,
                rollout_percentage=0,
                required_tiers=("full",),
                owner_plugin=context.plugin_id,
            )
        )
        context.define_flag(
            feature_flags.FlagDefinition(
                key="storage.high_capacity",
                name="High-capacity workspace storage",
                description="Enable administrator-approved 1 TiB and 2 TiB workspace storage profiles.",
                default_enabled=False,
                rollout_percentage=0,
                required_tiers=("full",),
                owner_plugin=context.plugin_id,
            )
        )
        context.add_agent_tool("mcp.call_tool", mcp_manager.call_tool)
        context.add_agent_tool("mcp.list_tools", mcp_manager.list_tools)
        context.add_health_check("feature-flag-store", self._flag_health)
        context.add_health_check("mcp-registry-store", self._mcp_health)
        context.on_startup(self._startup)

    @staticmethod
    def _startup(_app) -> None:
        with feature_flags.connect() as db:
            feature_flags.ensure_schema(db)
        with mcp_manager.connect() as db:
            mcp_manager.ensure_schema(db)

    @staticmethod
    def _flag_health() -> dict:
        with feature_flags.connect() as db:
            feature_flags.ensure_schema(db)
            count = int(db.execute("SELECT COUNT(*) FROM feature_flags").fetchone()[0])
        return {"state": "operational", "flags": count}

    @staticmethod
    def _mcp_health() -> dict:
        with mcp_manager.connect() as db:
            mcp_manager.ensure_schema(db)
            count = int(db.execute("SELECT COUNT(*) FROM mcp_servers").fetchone()[0])
        return {"state": "operational", "servers": count}


def create_plugin() -> ControlPlanePlugin:
    return ControlPlanePlugin()

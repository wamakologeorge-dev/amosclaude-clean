import json
from pathlib import Path

import pytest

from amoscloud_ai import feature_flags, mcp_manager
from amoscloud_ai.api.routes import auth
from amoscloud_ai.extensions.runtime import get_registry
from amoscloud_ai.main import create_app


ROOT = Path(__file__).resolve().parents[1]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _user(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> int:
    monkeypatch.setattr(auth, "DB_PATH", tmp_path / "auth.db")
    with auth._connect() as db:
        cursor = db.execute(
            """INSERT INTO users(name,email,password_hash,provider,is_admin,created_at)
               VALUES (?,?,?,?,?,?)""",
            (
                "Plugin Owner",
                "plugins@example.com",
                "hash",
                "password",
                1,
                "2026-07-27T00:00:00+00:00",
            ),
        )
        db.commit()
        return int(cursor.lastrowid)


def test_extension_routes_are_loaded_without_hardcoding_them_in_main() -> None:
    paths = {getattr(route, "path", "") for route in create_app().routes}
    assert {
        "/admin/extensions",
        "/api/v1/plugins/control-plane/registry",
        "/api/v1/plugins/control-plane/registry/health",
        "/api/v1/plugins/control-plane/flags",
        "/api/v1/plugins/control-plane/features/{key}",
        "/api/v1/plugins/control-plane/mcp/servers",
        "/api/v1/plugins/control-plane/mcp/servers/{server_id}/tools",
    }.issubset(paths)

    main = _source("amoscloud_ai/main.py")
    assert "extensions.router" not in main
    assert "mcp_manager" not in main
    assert "feature_flags" not in main


def test_drop_in_registry_discovers_the_control_plane_plugin() -> None:
    registry = get_registry()
    records = {item["plugin_id"]: item for item in registry.list_plugins()}
    assert "control-plane" in records
    record = records["control-plane"]
    assert record["source"].startswith("drop-in:amoscloud_ai.plugins.")
    assert record["status"] in {"mounted", "started"}
    assert "mcp-client-manager" in record["capabilities"]
    assert "control-plane.mcp.call_tool" in registry.agent_tools


def test_feature_flag_precedence_is_workspace_then_user_then_tier_then_rollout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = _user(tmp_path, monkeypatch)
    feature_flags.upsert_flag(
        key="workspace.live_collaboration",
        name="Live collaboration",
        description="test",
        enabled=True,
        rollout_percentage=100,
        required_tiers=[],
        owner_plugin="test",
        actor_user_id=user_id,
    )
    feature_flags.set_target(
        key="workspace.live_collaboration",
        target_type="tier",
        target_value="community",
        enabled=False,
        actor_user_id=user_id,
    )
    feature_flags.set_target(
        key="workspace.live_collaboration",
        target_type="user",
        target_value=str(user_id),
        enabled=True,
        actor_user_id=user_id,
    )
    feature_flags.set_target(
        key="workspace.live_collaboration",
        target_type="workspace",
        target_value="workspace-123",
        enabled=False,
        actor_user_id=user_id,
    )

    workspace = feature_flags.evaluate(
        "workspace.live_collaboration",
        user_id=user_id,
        workspace_id="workspace-123",
    )
    user = feature_flags.evaluate(
        "workspace.live_collaboration",
        user_id=user_id,
        workspace_id="workspace-456",
    )
    tier = feature_flags.evaluate(
        "workspace.live_collaboration",
        user_id=user_id + 999,
        tier="community",
    )

    assert workspace["enabled"] is False
    assert workspace["reason"] == "explicit_workspace_override"
    assert user["enabled"] is True
    assert user["reason"] == "explicit_user_override"
    assert tier["enabled"] is False
    assert tier["reason"] == "explicit_tier_override"


def test_percentage_rollout_is_deterministic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = _user(tmp_path, monkeypatch)
    feature_flags.upsert_flag(
        key="test.rollout",
        name="Rollout",
        description="test",
        enabled=True,
        rollout_percentage=37,
        required_tiers=[],
        owner_plugin="test",
        actor_user_id=user_id,
    )
    first = feature_flags.evaluate("test.rollout", user_id=user_id)
    second = feature_flags.evaluate("test.rollout", user_id=user_id)
    assert first == second
    assert first["bucket"] in range(100)
    assert first["enabled"] is (first["bucket"] < 37)


def test_mcp_credentials_are_environment_references_and_scopes_are_enforced(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = _user(tmp_path, monkeypatch)
    secret = "Bearer secret-value-that-must-never-enter-the-database"
    monkeypatch.setenv("MCP_TEST_TOKEN", secret)

    feature_flags.upsert_flag(
        key="mcp.integrations",
        name="MCP",
        description="test",
        enabled=True,
        rollout_percentage=100,
        required_tiers=[],
        owner_plugin="test",
        actor_user_id=user_id,
    )
    mcp_manager.upsert_server(
        server_id="jira-test",
        name="Jira test",
        description="test",
        endpoint="https://mcp.example.com/mcp",
        auth_header_name="Authorization",
        auth_secret_env="MCP_TEST_TOKEN",
        enabled=True,
        feature_flag_key="mcp.integrations",
        allowed_tools=["jira.search", "jira.issue.get"],
        timeout_seconds=20,
        created_by=user_id,
    )
    mcp_manager.set_scope("jira-test", "user", str(user_id))

    row = mcp_manager.authorized_server("jira-test", user_id=user_id)
    assert row["id"] == "jira-test"
    serialized = json.dumps(mcp_manager.list_servers(), sort_keys=True)
    assert secret not in serialized
    assert "MCP_TEST_TOKEN" in serialized
    assert "jira.search" in serialized

    with pytest.raises(mcp_manager.MCPManagerError, match="not assigned"):
        mcp_manager.authorized_server("jira-test", user_id=user_id + 1)


def test_mcp_endpoint_and_tool_boundaries_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AMOSCLAUD_MCP_ALLOW_PRIVATE_ENDPOINTS", raising=False)
    with pytest.raises(mcp_manager.MCPManagerError, match="must use HTTPS"):
        mcp_manager.validate_endpoint("http://127.0.0.1:9000/mcp", resolve_dns=False)
    with pytest.raises(mcp_manager.MCPManagerError, match="credentials"):
        mcp_manager.validate_endpoint(
            "https://user:password@example.com/mcp",
            resolve_dns=False,
        )
    assert (
        mcp_manager.validate_endpoint(
            "https://mcp.example.com/mcp",
            resolve_dns=False,
        )
        == "https://mcp.example.com/mcp"
    )


def test_drop_in_loader_sdk_pin_dashboard_and_storage_flag_contracts() -> None:
    runtime = _source("amoscloud_ai/extensions/runtime.py")
    registry = _source("amoscloud_ai/extensions/registry.py")
    manager = _source("amoscloud_ai/mcp_manager.py")
    requirements = _source("requirements.txt")
    dockerfile = _source("Dockerfile")
    dashboard = _source("web/extensions.html")
    dashboard_js = _source("web/extensions.js")
    storage = _source("amoscloud_ai/api/routes/storage_capacity.py")

    assert "pkgutil.iter_modules" in runtime
    assert "amoscloud_ai.plugins" in runtime
    assert "metadata.entry_points" in registry
    assert '"amosclaud.plugins"' in registry
    assert "streamable_http_client" in manager
    assert "ClientSession" in manager
    assert "follow_redirects=False" in manager
    assert "mcp>=1.27.2,<2" in requirements
    assert '"mcp>=1.27.2,<2"' in dockerfile
    assert "Plugins, MCP, and feature flags" in dashboard
    assert "/api/v1/plugins/control-plane" in dashboard_js
    assert '"storage.high_capacity"' in storage
    assert "_HIGH_CAPACITY_THRESHOLD_GIB" in storage

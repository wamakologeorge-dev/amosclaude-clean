import base64
import hashlib
import hmac
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import yaml

from amoscloud_ai import workspace_runtime
from amoscloud_ai.main import app
from amoscloud_ai.route_discovery import route_paths
from amoscloud_ai.workspace_runtime_service import check as check_workspace_runtime


ROOT = Path(__file__).resolve().parents[1]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_cloud_workspace_routes_are_mounted_on_the_real_app() -> None:
    paths = route_paths(app.routes)
    expected = {
        "/api/v1/cloud-workspaces/runtime",
        "/api/v1/cloud-workspaces/repositories/{repository_id}",
        "/api/v1/cloud-workspaces/repositories/{repository_id}/start",
        "/api/v1/cloud-workspaces/repositories/{repository_id}/stop",
        "/api/v1/cloud-workspaces/repositories/{repository_id}/terminal-ticket",
    }
    assert expected.issubset(paths)


def test_terminal_ticket_is_short_lived_signed_and_nonce_bound(monkeypatch) -> None:
    token = "runtime-test-token-that-is-long-and-random"
    monkeypatch.setenv("AMOSCLAUD_WORKSPACE_RUNTIME_TOKEN", token)
    monkeypatch.setenv("AMOSCLAUD_WORKSPACE_RUNTIME_URL", "https://runtime.example.test")
    monkeypatch.setenv("AMOSCLAUD_WORKSPACE_PUBLIC_URL", "https://terminal.example.test")

    before = 1_700_000_000
    monkeypatch.setattr(workspace_runtime.time, "time", lambda: before)
    result = workspace_runtime.terminal_ticket(
        {"id": "ws_0123456789abcdef", "repository_id": 7, "owner_id": 3},
        11,
    )

    parsed = urlparse(result["websocket_url"])
    assert parsed.scheme == "wss"
    assert parsed.netloc == "terminal.example.test"
    assert parsed.path == "/v1/terminal/ws_0123456789abcdef"
    ticket_value = parse_qs(parsed.query)["ticket"][0]
    raw = base64.urlsafe_b64decode(ticket_value + "=" * (-len(ticket_value) % 4))
    ticket = json.loads(raw)

    assert ticket["workspace_id"] == "ws_0123456789abcdef"
    assert ticket["user_id"] == 11
    assert ticket["expires_at"] == before + 120
    assert len(ticket["nonce"]) >= 16
    payload = (
        f"{ticket['workspace_id']}:{ticket['user_id']}:"
        f"{ticket['expires_at']}:{ticket['nonce']}"
    ).encode()
    expected = hmac.new(token.encode(), payload, hashlib.sha256).hexdigest()
    assert hmac.compare_digest(expected, ticket["signature"])


def test_runtime_source_enforces_container_isolation() -> None:
    source = _source("services/workspace_runtime/app.py")

    assert 'user="developer"' in source
    assert 'working_dir="/workspace"' in source
    assert "nano_cpus=int(CPU_LIMIT * 1_000_000_000)" in source
    assert 'mem_limit=f"{MEMORY_LIMIT}m"' in source
    assert "pids_limit=PIDS_LIMIT" in source
    assert 'cap_drop=["ALL"]' in source
    assert 'security_opt=["no-new-privileges:true"]' in source
    assert "read_only=True" in source
    assert 'network_kwargs = {"network_mode": "none"}' in source
    assert "CPU_LIMIT = min(" in source and "), 2.0)" in source
    assert "4096" in source
    assert "_repository_path(body.repository_id)" in source
    assert 'volumes={str(storage): {"bind": "/workspace", "mode": "rw"}}' in source
    assert '"docker",' in source and '"exec",' in source
    assert "pty.openpty()" in source
    assert "_verify_origin(websocket)" in source
    assert "Terminal ticket was already used" in source


def test_workspace_base_image_is_non_root() -> None:
    source = _source("services/workspace_runtime/workspace-image/Dockerfile")
    assert "useradd --uid 1000" in source
    assert "USER developer" in source
    assert "WORKDIR /workspace" in source
    assert "USER root" not in source


def test_runtime_stack_is_separate_and_owns_the_only_docker_socket_mount() -> None:
    compose = yaml.safe_load(_source("docker-compose.workspace-runtime.yml"))
    runtime = compose["services"]["workspace-runtime"]
    mounts = runtime["volumes"]

    assert "/var/run/docker.sock:/var/run/docker.sock" in mounts
    assert any("/var/lib/amosclaud/repositories" in item for item in mounts)
    assert runtime["ports"][0].startswith("127.0.0.1:")
    assert compose["networks"]["workspace-control"]["internal"] is True

    production_dockerfile = _source("Dockerfile")
    assert "/var/run/docker.sock" not in production_dockerfile


def test_cloud_policy_matches_hard_runtime_limits() -> None:
    policy = json.loads(_source("config/organization-settings.json"))
    limits = policy["sandbox_resource_limits"]

    assert policy["server_managed"] is True
    assert limits["max_cpu_cores"] == 2
    assert limits["max_memory_mb"] == 4096
    assert limits["max_processes"] == 512
    assert limits["run_as_user"] == "developer"
    assert limits["default_network"] == "none"
    assert limits["allow_internal_mesh_access"] is False
    assert policy["developer_overrides"]["allowed"] is False


def test_xterm_client_uses_signed_ticket_and_pinned_version() -> None:
    source = _source("web/cloud-workspace.js")

    assert "@xterm/xterm@5.5.0" in source
    assert "/terminal-ticket" in source
    assert "new WebSocket(ticket.websocket_url)" in source
    assert "socket.send(data)" in source
    assert "maximum 2 CPU cores" in source
    assert "maximum 4 GB RAM" in source
    assert "credentials: 'same-origin'" in source


def test_content_security_policy_has_no_wildcard_script_source() -> None:
    source = _source("amoscloud_ai/security.py")
    assert "script-src 'self' https://cdn.jsdelivr.net" in source
    assert "connect-src 'self' https: wss:" in source
    assert "script-src *" not in source
    assert "unsafe-eval" not in source


def test_command_center_absorbs_amosclaud1_into_one_program() -> None:
    source = _source("web/command-center.html")
    assert "former Amosclaud1 dashboard" in source
    assert "amosclaude-clean" in source
    assert "One repository. One runtime model. One evidence trail." in source
    assert "2 CPU · 4 GB · non-root" in source
    assert "No separate production runtime is created from it." in source


def test_unconfigured_runtime_is_reported_truthfully(monkeypatch) -> None:
    monkeypatch.delenv("AMOSCLAUD_WORKSPACE_RUNTIME_URL", raising=False)
    monkeypatch.delenv("AMOSCLAUD_WORKSPACE_RUNTIME_TOKEN", raising=False)
    result = check_workspace_runtime()
    assert result["state"] == "not_configured"
    assert "cannot start" in result["explanation"]

from pathlib import Path

import pytest

from amoscloud_ai import workspace_provider
from workspace_worker import runtime


def _config(tmp_path: Path) -> runtime.WorkspaceRuntimeConfig:
    repositories = tmp_path / "repositories"
    (repositories / "7").mkdir(parents=True)
    return runtime.WorkspaceRuntimeConfig(
        docker="/usr/bin/docker",
        storage_root=tmp_path / "workspaces",
        repositories_root=repositories,
        image="ghcr.io/coder/code-server:4.96.4",
        network="amosclaud-workspace-internal",
        user="1000:1000",
        max_cpu=2.0,
        max_memory_mb=4096,
        max_pids=512,
        editor_url_template="https://www.amosclaud.com/workspaces/{workspace_id}/editor",
        terminal_url_template="wss://www.amosclaud.com/workspaces/{workspace_id}/terminal",
    )


def _value_after(command: list[str], option: str) -> str:
    return command[command.index(option) + 1]


def test_workspace_container_command_is_non_root_and_resource_bounded(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    command = runtime.build_create_command(
        config=config,
        workspace_id="ws_12345678",
        repository_id=7,
        cpu=200,
        memory_mb=200_000,
        pids=20_000,
    )

    assert _value_after(command, "--user") == "1000:1000"
    assert _value_after(command, "--cpus") == "2.0"
    assert _value_after(command, "--memory") == "4096m"
    assert _value_after(command, "--memory-swap") == "4096m"
    assert _value_after(command, "--pids-limit") == "512"
    assert "--read-only" in command
    assert command[command.index("--cap-drop") + 1] == "ALL"
    assert command[command.index("--security-opt") + 1] == "no-new-privileges=true"
    assert "--privileged" not in command
    assert "--publish" not in command
    assert "-p" not in command
    assert "/var/run/docker.sock" not in " ".join(command)
    assert "DATABASE_URL" not in " ".join(command)
    assert "GITHUB_TOKEN" not in " ".join(command)


def test_workspace_mounts_only_repository_and_editor_state(tmp_path: Path) -> None:
    command = runtime.build_create_command(
        config=_config(tmp_path),
        workspace_id="ws_abcdefgh",
        repository_id=7,
        cpu=1,
        memory_mb=2048,
        pids=256,
    )
    mounts = [
        command[index + 1]
        for index, value in enumerate(command)
        if value == "--mount"
    ]

    assert len(mounts) == 2
    assert any("dst=/home/coder/project,rw" in mount for mount in mounts)
    assert any("dst=/home/coder/.local/share/code-server,rw" in mount for mount in mounts)
    assert all("docker.sock" not in mount for mount in mounts)


def test_workspace_runtime_rejects_root_identity() -> None:
    with pytest.raises(runtime.WorkspaceRuntimeError):
        runtime._numeric_non_root_user("0:0")
    with pytest.raises(runtime.WorkspaceRuntimeError):
        runtime._numeric_non_root_user("root:root")


def test_workspace_gateway_requires_tls(tmp_path: Path) -> None:
    config = _config(tmp_path)
    assert runtime._format_url(
        config.editor_url_template,
        "ws_12345678",
        "amosclaud-ws_12345678",
    ).startswith("https://")
    assert runtime._format_url(
        config.terminal_url_template,
        "ws_12345678",
        "amosclaud-ws_12345678",
    ).startswith("wss://")

    with pytest.raises(runtime.WorkspaceRuntimeError):
        runtime._format_url(
            "http://workspace.internal/{workspace_id}",
            "ws_12345678",
            "amosclaud-ws_12345678",
        )


def test_workspace_provider_reads_file_mounted_token(tmp_path: Path, monkeypatch) -> None:
    token_file = tmp_path / "provider-token"
    token_file.write_text("private-service-token\n", encoding="utf-8")
    monkeypatch.delenv("AMOSCLAUD_WORKSPACE_PROVIDER_TOKEN", raising=False)
    monkeypatch.setenv("AMOSCLAUD_WORKSPACE_PROVIDER_TOKEN_FILE", str(token_file))
    monkeypatch.setenv("AMOSCLAUD_WORKSPACE_PROVIDER_URL", "http://workspace-worker:8092")

    config = workspace_provider.provider_config()

    assert config.token == "private-service-token"
    assert config.base_url == "http://workspace-worker:8092"

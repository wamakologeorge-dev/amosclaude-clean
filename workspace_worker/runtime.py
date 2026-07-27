"""Docker-backed runtime for persistent Amosclaud developer workspaces.

The worker is intentionally separate from the public API. Every Docker command
is built as an argument vector, the container is non-root, and the workspace is
attached only to a private internal bridge network.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess  # nosec B404
from dataclasses import dataclass
from pathlib import Path
from typing import Any


WORKSPACE_ID_RE = re.compile(r"^ws_[A-Za-z0-9_-]{8,64}$")
IMAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/:@-]{1,254}$")


class WorkspaceRuntimeError(RuntimeError):
    """Raised when a workspace cannot be provisioned safely."""


@dataclass(frozen=True, slots=True)
class WorkspaceRuntimeConfig:
    docker: str
    storage_root: Path
    repositories_root: Path
    image: str
    network: str
    user: str
    max_cpu: float
    max_memory_mb: int
    max_pids: int
    editor_url_template: str
    terminal_url_template: str


def _numeric_non_root_user(value: str) -> tuple[int, int]:
    parts = value.split(":", 1)
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        raise WorkspaceRuntimeError(
            "AMOSCLAUD_WORKSPACE_USER must be a numeric non-root UID:GID"
        )
    uid, gid = (int(part) for part in parts)
    if uid <= 0 or gid <= 0:
        raise WorkspaceRuntimeError(
            "AMOSCLAUD_WORKSPACE_USER must be a numeric non-root UID:GID"
        )
    return uid, gid


def runtime_config() -> WorkspaceRuntimeConfig:
    docker = shutil.which(os.getenv("AMOSCLAUD_DOCKER_BINARY", "docker"))
    if not docker:
        raise WorkspaceRuntimeError("Docker is not available on the workspace worker")

    image = os.getenv("AMOSCLAUD_WORKSPACE_IMAGE", "").strip()
    if not image or not IMAGE_RE.fullmatch(image):
        raise WorkspaceRuntimeError(
            "AMOSCLAUD_WORKSPACE_IMAGE must name one approved workspace image"
        )

    user = os.getenv("AMOSCLAUD_WORKSPACE_USER", "1000:1000").strip()
    _numeric_non_root_user(user)
    return WorkspaceRuntimeConfig(
        docker=docker,
        storage_root=Path(
            os.getenv(
                "AMOSCLAUD_WORKSPACE_STORAGE_ROOT",
                "/var/lib/amosclaud/workspaces",
            )
        ).resolve(),
        repositories_root=Path(
            os.getenv(
                "AMOSCLAUD_REPOSITORY_STORAGE_ROOT",
                "/var/lib/amosclaud/repositories",
            )
        ).resolve(),
        image=image,
        network=os.getenv(
            "AMOSCLAUD_WORKSPACE_NETWORK",
            "amosclaud-workspace-internal",
        ).strip(),
        user=user,
        max_cpu=max(0.25, min(float(os.getenv("AMOSCLAUD_WORKSPACE_MAX_CPU", "2")), 2.0)),
        max_memory_mb=max(
            256,
            min(int(os.getenv("AMOSCLAUD_WORKSPACE_MAX_MEMORY_MB", "4096")), 4096),
        ),
        max_pids=max(
            32,
            min(int(os.getenv("AMOSCLAUD_WORKSPACE_MAX_PIDS", "512")), 512),
        ),
        editor_url_template=os.getenv(
            "AMOSCLAUD_WORKSPACE_EDITOR_URL_TEMPLATE", ""
        ).strip(),
        terminal_url_template=os.getenv(
            "AMOSCLAUD_WORKSPACE_TERMINAL_URL_TEMPLATE", ""
        ).strip(),
    )


def validate_workspace_id(workspace_id: str) -> str:
    if not WORKSPACE_ID_RE.fullmatch(workspace_id):
        raise WorkspaceRuntimeError("Invalid workspace identifier")
    return workspace_id


def container_name(workspace_id: str) -> str:
    validate_workspace_id(workspace_id)
    return f"amosclaud-{workspace_id.lower()}"


def _run(
    config: WorkspaceRuntimeConfig,
    arguments: list[str],
    *,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(  # nosec B603
            [config.docker, *arguments],
            check=check,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=60,
        )
    except subprocess.TimeoutExpired as exc:
        raise WorkspaceRuntimeError("Workspace container command timed out") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "Docker rejected the request").strip()
        raise WorkspaceRuntimeError(detail[:1000]) from exc


def ensure_private_network(config: WorkspaceRuntimeConfig) -> None:
    if not config.network or len(config.network) > 100:
        raise WorkspaceRuntimeError("Invalid workspace network name")
    inspected = _run(config, ["network", "inspect", config.network], check=False)
    if inspected.returncode == 0:
        return
    created = _run(
        config,
        [
            "network",
            "create",
            "--driver",
            "bridge",
            "--internal",
            "--label",
            "amosclaud.network=workspace",
            config.network,
        ],
        check=False,
    )
    if created.returncode != 0:
        # Another worker process may have created it after our inspect.
        verified = _run(config, ["network", "inspect", config.network], check=False)
        if verified.returncode != 0:
            raise WorkspaceRuntimeError("Unable to create the private workspace network")


def _repository_path(config: WorkspaceRuntimeConfig, repository_id: int) -> Path:
    if repository_id < 1:
        raise WorkspaceRuntimeError("Invalid repository identifier")
    root = config.repositories_root
    candidate = (root / str(repository_id)).resolve()
    if not candidate.is_relative_to(root):
        raise WorkspaceRuntimeError("Repository path escaped the storage root")
    if not candidate.is_dir():
        raise WorkspaceRuntimeError(
            "Repository storage is unavailable on the workspace worker"
        )
    return candidate


def _workspace_state_path(
    config: WorkspaceRuntimeConfig,
    workspace_id: str,
) -> Path:
    validate_workspace_id(workspace_id)
    root = config.storage_root
    path = (root / workspace_id).resolve()
    if not path.is_relative_to(root):
        raise WorkspaceRuntimeError("Workspace path escaped the storage root")
    path.mkdir(parents=True, exist_ok=True)
    state = path / "code-server"
    state.mkdir(parents=True, exist_ok=True)
    return state


def _format_url(template: str, workspace_id: str, name: str) -> str | None:
    if not template:
        return None
    try:
        rendered = template.format(
            workspace_id=workspace_id,
            container_name=name,
        )
    except (KeyError, ValueError) as exc:
        raise WorkspaceRuntimeError("Invalid workspace URL template") from exc
    if not rendered.startswith(("https://", "wss://")):
        raise WorkspaceRuntimeError(
            "Workspace gateway URL templates must use HTTPS or WSS"
        )
    return rendered


def build_create_command(
    *,
    config: WorkspaceRuntimeConfig,
    workspace_id: str,
    repository_id: int,
    cpu: float,
    memory_mb: int,
    pids: int,
) -> list[str]:
    name = container_name(workspace_id)
    repository = _repository_path(config, repository_id)
    state = _workspace_state_path(config, workspace_id)
    uid, gid = _numeric_non_root_user(config.user)
    bounded_cpu = max(0.25, min(float(cpu), config.max_cpu, 2.0))
    bounded_memory = max(256, min(int(memory_mb), config.max_memory_mb, 4096))
    bounded_pids = max(32, min(int(pids), config.max_pids, 512))

    return [
        "create",
        "--name",
        name,
        "--hostname",
        "workspace",
        "--label",
        f"amosclaud.workspace.id={workspace_id}",
        "--label",
        f"amosclaud.repository.id={repository_id}",
        "--network",
        config.network,
        "--cpus",
        str(bounded_cpu),
        "--memory",
        f"{bounded_memory}m",
        "--memory-swap",
        f"{bounded_memory}m",
        "--pids-limit",
        str(bounded_pids),
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges=true",
        "--user",
        config.user,
        "--tmpfs",
        f"/tmp:rw,noexec,nosuid,nodev,size=256m,uid={uid},gid={gid}",
        "--tmpfs",
        (
            "/home/coder/.cache:rw,noexec,nosuid,nodev,size=256m,"
            f"uid={uid},gid={gid}"
        ),
        "--mount",
        f"type=bind,src={repository},dst=/home/coder/project,rw",
        "--mount",
        f"type=bind,src={state},dst=/home/coder/.local/share/code-server,rw",
        "--workdir",
        "/home/coder/project",
        "--env",
        "HOME=/home/coder",
        "--env",
        "SHELL=/bin/bash",
        "--env",
        "CS_DISABLE_GETTING_STARTED_OVERRIDE=1",
        config.image,
        "--bind-addr",
        "0.0.0.0:8080",
        "--auth",
        "none",
        "--disable-telemetry",
        "--disable-update-check",
        "--disable-proxy",
        "/home/coder/project",
    ]


def _inspect_state(config: WorkspaceRuntimeConfig, name: str) -> dict[str, Any] | None:
    result = _run(
        config,
        ["inspect", "--format", "{{json .State}}", name],
        check=False,
    )
    if result.returncode != 0:
        return None
    try:
        value = json.loads(result.stdout.strip())
    except json.JSONDecodeError as exc:
        raise WorkspaceRuntimeError("Docker returned invalid workspace state") from exc
    if not isinstance(value, dict):
        raise WorkspaceRuntimeError("Docker returned invalid workspace state")
    return value


def describe(config: WorkspaceRuntimeConfig, workspace_id: str) -> dict[str, Any]:
    name = container_name(workspace_id)
    state = _inspect_state(config, name)
    if state is None:
        status = "stopped"
        exists = False
    elif bool(state.get("Running")):
        status = "running"
        exists = True
    elif int(state.get("ExitCode") or 0) != 0:
        status = "failed"
        exists = True
    else:
        status = "stopped"
        exists = True
    return {
        "workspace_id": workspace_id,
        "provider": "docker-worker",
        "container_name": name,
        "exists": exists,
        "status": status,
        "editor_url": _format_url(
            config.editor_url_template,
            workspace_id,
            name,
        ),
        "terminal_url": _format_url(
            config.terminal_url_template,
            workspace_id,
            name,
        ),
    }


def provision(
    *,
    workspace_id: str,
    repository_id: int,
    cpu: float,
    memory_mb: int,
    pids: int,
) -> dict[str, Any]:
    config = runtime_config()
    ensure_private_network(config)
    current = describe(config, workspace_id)
    if current["exists"]:
        return current
    command = build_create_command(
        config=config,
        workspace_id=workspace_id,
        repository_id=repository_id,
        cpu=cpu,
        memory_mb=memory_mb,
        pids=pids,
    )
    _run(config, command)
    return describe(config, workspace_id)


def start(workspace_id: str) -> dict[str, Any]:
    config = runtime_config()
    name = container_name(workspace_id)
    if _inspect_state(config, name) is None:
        raise WorkspaceRuntimeError("Workspace container has not been provisioned")
    _run(config, ["start", name])
    return describe(config, workspace_id)


def stop(workspace_id: str) -> dict[str, Any]:
    config = runtime_config()
    name = container_name(workspace_id)
    if _inspect_state(config, name) is not None:
        _run(config, ["stop", "--time", "10", name])
    return describe(config, workspace_id)


def restart(workspace_id: str) -> dict[str, Any]:
    config = runtime_config()
    name = container_name(workspace_id)
    if _inspect_state(config, name) is None:
        raise WorkspaceRuntimeError("Workspace container has not been provisioned")
    _run(config, ["restart", "--time", "10", name])
    return describe(config, workspace_id)


def delete(workspace_id: str) -> dict[str, Any]:
    config = runtime_config()
    name = container_name(workspace_id)
    if _inspect_state(config, name) is not None:
        _run(config, ["rm", "--force", name])
    # Repository files are intentionally not removed. They live in shared,
    # persistent repository storage and remain the source of truth.
    return {
        "workspace_id": workspace_id,
        "provider": "docker-worker",
        "container_name": name,
        "exists": False,
        "status": "deleted",
        "editor_url": None,
        "terminal_url": None,
    }

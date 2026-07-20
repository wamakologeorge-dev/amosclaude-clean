"""Control an installed Amosclaud workspace through the unified platform compose file."""

from __future__ import annotations

import argparse
import json
import os
import shutil

# Only the resolved Docker executable is called; shell execution is never enabled.
import subprocess  # nosec B404
import sys
from dataclasses import dataclass
from pathlib import Path

from shared.runtime import REQUIRED_PLATFORM_ENV, ServiceName, platform_endpoints


class WorkspaceError(RuntimeError):
    """Raised when the Amosclaud workspace cannot be safely controlled."""


@dataclass(frozen=True)
class WorkspaceLayout:
    root: Path
    app: Path
    compose_file: Path
    projects: Path
    config: Path
    data: Path
    logs: Path


def _discover_at(candidate: Path) -> WorkspaceLayout | None:
    """Resolve unified, packaged, and source workspace layouts.

    The unified repository layout is preferred. The two historical self-hosted
    layouts remain supported so existing Amosclaud installations do not need to
    reorganize their repositories merely to use the newer platform controller.
    """
    unified = candidate / "Infrastructure" / "docker-compose.yml"
    if unified.is_file():
        return WorkspaceLayout(
            root=candidate,
            app=candidate,
            compose_file=unified,
            projects=candidate / "data" / "repositories",
            config=candidate / "config",
            data=candidate / "data",
            logs=candidate / "data" / "logs",
        )

    # Installed distribution: <root>/app/docker-compose.selfhost.yml
    packaged = candidate / "app" / "docker-compose.selfhost.yml"
    if packaged.is_file():
        return WorkspaceLayout(
            root=candidate,
            app=candidate / "app",
            compose_file=packaged,
            projects=candidate / "workspace" / "projects",
            config=candidate / "config",
            data=candidate / "data",
            logs=candidate / "data" / "logs",
        )

    # Source checkout: <root>/docker-compose.selfhost.yml
    legacy = candidate / "docker-compose.selfhost.yml"
    if legacy.is_file():
        return WorkspaceLayout(
            root=candidate,
            app=candidate,
            compose_file=legacy,
            projects=candidate / "AmosclaudWorkspace",
            config=candidate / "config",
            data=candidate / "data",
            logs=candidate / "data" / "logs",
        )

    return None


def discover_layout(start: Path | None = None) -> WorkspaceLayout:
    location = (start or Path.cwd()).resolve()

    # Starting inside the packaged app must resolve its parent as the workspace
    # root rather than treating the app directory as a source checkout.
    if location.name == "app" and (location / "docker-compose.selfhost.yml").is_file():
        parent_layout = _discover_at(location.parent)
        if parent_layout is not None:
            return parent_layout

    for candidate in (location, *location.parents):
        layout = _discover_at(candidate)
        if layout is not None:
            return layout

    raise WorkspaceError(
        "Run this command from an Amosclaud repository or installed workspace"
    )


def ensure_layout(layout: WorkspaceLayout) -> None:
    for directory in (
        layout.projects,
        layout.config,
        layout.data,
        layout.logs,
    ):
        directory.mkdir(parents=True, exist_ok=True)


def _compose(layout: WorkspaceLayout, *arguments: str, check: bool = True) -> int:
    docker = shutil.which("docker")
    if not docker:
        raise WorkspaceError("Docker is not installed or is not available on PATH")
    completed = subprocess.run(  # nosec B603
        [
            docker,
            "compose",
            "-f",
            str(layout.compose_file),
            *arguments,
        ],
        cwd=layout.root,
        check=check,
    )
    return completed.returncode


def _runner_profile(layout: WorkspaceLayout) -> tuple[str, ...]:
    runner_env = layout.app / ".env.runner"
    if runner_env.is_file() and "AMOSCLAUD_RUNNER_ID=" in runner_env.read_text(
        encoding="utf-8"
    ):
        return ("--profile", "connected-runner")
    return ()


def _compose_contract(layout: WorkspaceLayout) -> dict[str, object]:
    text = layout.compose_file.read_text(encoding="utf-8")
    endpoints = platform_endpoints()
    required_services = {
        ServiceName.PLATFORM: "amosclaud:",
        ServiceName.MODEL: "model:",
        ServiceName.CREDENTIAL_AUTHORITY: "credential-authority:",
        ServiceName.METRICS: "metrics:",
        ServiceName.REDIS: "redis:",
    }
    service_presence = {
        service.value: marker in text for service, marker in required_services.items()
    }
    return {
        "services": service_presence,
        "service_urls": {
            service.value: endpoint.base_url for service, endpoint in endpoints.items()
        },
        "required_environment": {
            name: f"{name}:" in text for name in REQUIRED_PLATFORM_ENV
        },
        "autonomous_enabled": 'AMOSCLAUD_AUTONOMOUS_ENABLED: "true"' in text,
        "fixer_enabled": 'AMOSCLAUD_FIXER_ENABLED: "true"' in text,
        "verification_required": 'AMOSCLAUD_REQUIRE_VERIFICATION: "true"' in text,
        "default_branch_protected": (
            'AMOSCLAUD_PROTECT_DEFAULT_BRANCH: "true"' in text
        ),
    }


def doctor(layout: WorkspaceLayout) -> dict:
    ensure_layout(layout)
    docker = shutil.which("docker")
    contract = _compose_contract(layout)
    report = {
        "workspace_root": str(layout.root),
        "compose_file": str(layout.compose_file),
        "application_found": layout.compose_file.is_file(),
        "configuration_found": layout.config.is_dir(),
        "docker_found": bool(docker),
        "projects_directory": str(layout.projects),
        "projects_writable": os.access(layout.projects, os.W_OK),
        "platform_contract": contract,
    }
    if docker:
        report["docker_ready"] = (
            subprocess.run(  # nosec B603
                [docker, "info"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            ).returncode
            == 0
        )
    else:
        report["docker_ready"] = False

    # Legacy compose files do not contain the unified multi-service contract.
    # They remain controllable, but only the unified stack can be fully ready.
    unified = layout.compose_file.name == "docker-compose.yml"
    services_ready = all(contract["services"].values()) if unified else True
    env_ready = all(contract["required_environment"].values()) if unified else True
    policy_ready = (
        all(
            bool(contract[key])
            for key in (
                "autonomous_enabled",
                "fixer_enabled",
                "verification_required",
                "default_branch_protected",
            )
        )
        if unified
        else True
    )
    report["ready"] = all(
        (
            report["application_found"],
            report["configuration_found"],
            report["docker_found"],
            report["docker_ready"],
            report["projects_writable"],
            services_ready,
            env_ready,
            policy_ready,
        )
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(prog="amosclaud-workspace")
    parser.add_argument(
        "command",
        choices=["doctor", "start", "stop", "status", "logs"],
        nargs="?",
        default="doctor",
    )
    args = parser.parse_args()
    try:
        layout = discover_layout()
        ensure_layout(layout)
        if args.command == "doctor":
            print(json.dumps(doctor(layout), indent=2))
        elif args.command == "start":
            _compose(layout, *_runner_profile(layout), "up", "-d")
        elif args.command == "stop":
            _compose(layout, "down")
        elif args.command == "status":
            _compose(layout, "ps")
        elif args.command == "logs":
            _compose(layout, "logs", "--tail", "200")
    except WorkspaceError as exc:
        print(f"Amosclaud workspace error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()

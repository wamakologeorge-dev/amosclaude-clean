"""Control an installed Amosclaud workspace through the unified platform compose file."""

from __future__ import annotations

import argparse
import json
import os
import shutil

# Only the resolved Docker executable is called; shell execution is never enabled.
import subprocess  # nosec B404
import sys
from dataclasses import asdict, dataclass
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


def _find_compose(candidate: Path) -> tuple[Path, Path] | None:
    """Return the application directory and supported Compose file."""
    unified = candidate / "Infrastructure" / "docker-compose.yml"
    if unified.is_file():
        return candidate, unified

    installed = candidate / "app" / "docker-compose.selfhost.yml"
    if installed.is_file():
        return candidate / "app", installed

    legacy = candidate / "docker-compose.selfhost.yml"
    if legacy.is_file():
        return candidate, legacy

    return None


def discover_layout(start: Path | None = None) -> WorkspaceLayout:
    location = (start or Path.cwd()).resolve()
    candidates = [location, *location.parents]

    discovered: tuple[Path, Path, Path] | None = None
    for candidate in candidates:
        compose = _find_compose(candidate)
        if compose:
            app, compose_file = compose
            discovered = (candidate, app, compose_file)
            break

    if not discovered:
        raise WorkspaceError(
            "Run this command from an Amosclaud repository or installed workspace"
        )

    root, app, compose_file = discovered
    projects = (
        root / "data" / "repositories"
        if compose_file.name == "docker-compose.yml"
        else root / "workspace" / "projects"
    )
    return WorkspaceLayout(
        root=root,
        app=app,
        compose_file=compose_file,
        projects=projects,
        config=root / "config",
        data=root / "data",
        logs=root / "data" / "logs",
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
        "configuration_found": (layout.root / "config").is_dir(),
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

    services_ready = all(contract["services"].values())
    env_ready = all(contract["required_environment"].values())
    policy_ready = all(
        bool(contract[key])
        for key in (
            "autonomous_enabled",
            "fixer_enabled",
            "verification_required",
            "default_branch_protected",
        )
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

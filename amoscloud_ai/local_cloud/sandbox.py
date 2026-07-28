"""Hardened container execution profiles for untrusted local workspace checks."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path


class SandboxError(RuntimeError):
    """Raised when a sandbox profile or target is unsafe."""


_IMAGE = re.compile(
    r"^[A-Za-z0-9]+(?:(?:[._-]|/)[A-Za-z0-9]+)*(?::[A-Za-z0-9._-]+)?$"
)


@dataclass(frozen=True)
class SandboxPolicy:
    network: str = "none"
    memory: str = "1g"
    cpus: str = "1.0"
    pids_limit: int = 128
    tmpfs_size: str = "256m"
    user: str = "65534:65534"

    ACTIONS = {
        "python_tests": (
            "python",
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
        ),
        "python_import_check": (
            "python",
            "-c",
            (
                "import pathlib,py_compile;"
                "[py_compile.compile(str(p),doraise=True) "
                "for p in pathlib.Path('/workspace').rglob('*.py')]"
            ),
        ),
    }

    def docker_command(
        self,
        *,
        workspace: Path,
        image: str,
        action: str,
    ) -> list[str]:
        raw = Path(workspace).expanduser()
        absolute = Path(os.path.abspath(raw))
        for component in (absolute, *absolute.parents):
            if component.exists() and component.is_symlink():
                raise SandboxError(
                    "Sandbox workspace path cannot contain symlinks"
                )
        root = absolute.resolve(strict=True)
        if not root.is_dir():
            raise SandboxError("Sandbox workspace must be a directory")
        if not _IMAGE.fullmatch(str(image or "")):
            raise SandboxError("Sandbox image reference is invalid")
        try:
            command = self.ACTIONS[action]
        except KeyError as exc:
            raise SandboxError("Unsupported sandbox action") from exc
        if self.network not in {"none", "bridge"}:
            raise SandboxError("Unsupported sandbox network mode")
        if self.pids_limit < 16 or self.pids_limit > 4096:
            raise SandboxError("Sandbox PID limit is invalid")
        source = str(root)
        return [
            "docker",
            "run",
            "--rm",
            "--interactive=false",
            "--network",
            self.network,
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            str(self.pids_limit),
            "--memory",
            self.memory,
            "--cpus",
            self.cpus,
            "--user",
            self.user,
            "--tmpfs",
            f"/tmp:rw,noexec,nosuid,nodev,size={self.tmpfs_size}",
            "--mount",
            f"type=bind,src={source},dst=/workspace,readonly",
            "--workdir",
            "/workspace",
            "--env",
            "HOME=/tmp",
            "--env",
            "TMPDIR=/tmp",
            "--env",
            "PYTHONDONTWRITEBYTECODE=1",
            "--env",
            "PYTHONUNBUFFERED=1",
            image,
            *command,
        ]

    def summary(self) -> dict[str, object]:
        return {
            "runtime": "docker",
            "network": self.network,
            "read_only_rootfs": True,
            "workspace_read_only": True,
            "capabilities_dropped": "ALL",
            "no_new_privileges": True,
            "pids_limit": self.pids_limit,
            "memory": self.memory,
            "cpus": self.cpus,
            "user": self.user,
            "docker_socket_mounted": False,
            "vault_mounted": False,
            "supported_actions": sorted(self.ACTIONS),
        }


def policy_from_environment() -> SandboxPolicy:
    """Load only bounded resource limits from local operator configuration."""

    try:
        pids_limit = int(os.getenv("AMOSCLAUD_SANDBOX_PIDS_LIMIT", "128"))
    except ValueError as exc:
        raise SandboxError("AMOSCLAUD_SANDBOX_PIDS_LIMIT must be an integer") from exc
    return SandboxPolicy(
        network=os.getenv("AMOSCLAUD_SANDBOX_NETWORK", "none").strip().lower(),
        memory=os.getenv("AMOSCLAUD_SANDBOX_MEMORY", "1g").strip(),
        cpus=os.getenv("AMOSCLAUD_SANDBOX_CPUS", "1.0").strip(),
        pids_limit=pids_limit,
        tmpfs_size=os.getenv("AMOSCLAUD_SANDBOX_TMPFS", "256m").strip(),
        user=os.getenv("AMOSCLAUD_SANDBOX_USER", "65534:65534").strip(),
    )

"""Runtime helpers for repository-bound Amosclaud security grants."""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
from pathlib import Path

from .command_bus import SecurityAuthority

_SAFE_NAME = re.compile(r"[^A-Za-z0-9_.:-]+")


def repository_identity(workspace: Path | str, explicit: str | None = None) -> str:
    if explicit and "/" in explicit:
        return explicit.strip()
    configured = os.getenv("GITHUB_REPOSITORY", "").strip()
    if configured and "/" in configured:
        return configured
    root = Path(workspace).resolve()
    name = _SAFE_NAME.sub("-", root.name).strip("-.") or "workspace"
    return f"local/{name}"


def target_revision(workspace: Path | str) -> str:
    root = Path(workspace).resolve()
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    candidate = result.stdout.strip()
    if result.returncode == 0 and re.fullmatch(r"[0-9a-fA-F]{40,64}", candidate):
        return candidate.lower()
    material = f"{root}:{root.stat().st_mtime_ns if root.exists() else 0}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def security_state_path(workspace: Path | str) -> Path:
    configured = os.getenv(SecurityAuthority.STATE_ENV, "").strip()
    if configured:
        return Path(configured)
    root = Path(workspace).resolve()
    git_dir = root / ".git"
    if git_dir.is_dir():
        return git_dir / "amosclaud-command-bus.db"
    data_root = Path(os.getenv("AMOSCLAUD_SECURITY_DATA_ROOT", "./data/security"))
    identity = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:16]
    return data_root / f"{identity}.db"


def authority_for_workspace(
    workspace: Path | str,
    *,
    required: bool,
) -> SecurityAuthority | None:
    return SecurityAuthority.from_environment(
        state_path=security_state_path(workspace),
        required=required,
    )

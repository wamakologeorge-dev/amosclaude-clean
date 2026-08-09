"""Runtime helpers for repository-bound Amosclaud security grants."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import subprocess
from pathlib import Path

from .command_bus import SecurityAuthority

_SAFE_NAME = re.compile(r"[^A-Za-z0-9_.:-]+")
_TRUSTED_WRITE_ASSOCIATIONS = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})
_EPHEMERAL_AUTHORITIES: dict[Path, SecurityAuthority] = {}


def _validated_workspace_root(workspace: Path | str) -> Path:
    base = Path(os.getenv("AMOSCLAUD_WORKSPACE_ROOT", ".")).resolve()
    raw_workspace = str(workspace or ".").strip()
    if "\x00" in raw_workspace:
        raise ValueError("Invalid workspace path")

    workspace_path = Path(raw_workspace)
    if workspace_path.is_absolute():
        raise ValueError("Workspace must be a relative path")
    if ".." in workspace_path.parts:
        raise ValueError("Workspace escapes allowed root")

    root = (base / workspace_path).resolve()
    try:
        root.relative_to(base)
    except ValueError as exc:
        raise ValueError("Workspace escapes allowed root") from exc
    return root


def repository_identity(workspace: Path | str, explicit: str | None = None) -> str:
    if explicit and "/" in explicit:
        return explicit.strip()
    configured = os.getenv("GITHUB_REPOSITORY", "").strip()
    if configured and "/" in configured:
        return configured
    root = _validated_workspace_root(workspace)
    name = _SAFE_NAME.sub("-", root.name).strip("-.") or "workspace"
    return f"local/{name}"


def target_revision(workspace: Path | str) -> str:
    root = _validated_workspace_root(workspace)
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
    root = _validated_workspace_root(workspace)
    git_dir = root / ".git"
    if git_dir.is_dir():
        return git_dir / "amosclaud-command-bus.db"
    data_root = Path(os.getenv("AMOSCLAUD_SECURITY_DATA_ROOT", "./data/security"))
    identity = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:16]
    return data_root / f"{identity}.db"


def _trusted_github_edit_context() -> bool:
    """Allow a one-run authority only for trusted Amosclaud Bot fix comments.

    The generated signing key exists only in this Python process. It is never
    written to the repository, workflow output, model prompt, or environment.
    All normal capability, path, verification, and publication restrictions
    still apply.
    """

    if os.getenv("GITHUB_ACTIONS", "").strip().lower() != "true":
        return False
    if os.getenv("GITHUB_EVENT_NAME", "").strip() != "issue_comment":
        return False
    if os.getenv("GITHUB_WORKFLOW", "").strip() != "Amosclaud Bot":
        return False

    event_path = Path(os.getenv("GITHUB_EVENT_PATH", "").strip())
    if not event_path.is_file():
        return False
    try:
        payload = json.loads(event_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict):
        return False

    comment = payload.get("comment")
    if not isinstance(comment, dict):
        return False
    association = str(comment.get("author_association") or "NONE").upper()
    if association not in _TRUSTED_WRITE_ASSOCIATIONS:
        return False

    body = " ".join(str(comment.get("body") or "").strip().lower().split())
    return body.startswith("@amosclaud ") or body.startswith("@amosclaud-bot ")


def authority_for_workspace(
    workspace: Path | str,
    *,
    required: bool,
) -> SecurityAuthority | None:
    root = _validated_workspace_root(workspace)
    state_path = security_state_path(root)
    configured = SecurityAuthority.from_environment(
        state_path=state_path,
        required=False,
    )
    if configured is not None or not required:
        return configured

    if not _trusted_github_edit_context():
        return SecurityAuthority.from_environment(
            state_path=state_path,
            required=True,
        )

    authority = _EPHEMERAL_AUTHORITIES.get(root)
    if authority is None:
        authority = SecurityAuthority(secrets.token_urlsafe(48), state_path)
        _EPHEMERAL_AUTHORITIES[root] = authority
    return authority

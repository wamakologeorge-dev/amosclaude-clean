"""Repository-local Amosclaud startup control.

The ``.amosclaud`` directory is the first repository configuration layer.  This
module deliberately loads configuration and policy metadata only; it never
executes repair scripts, mutates source files, commits, or pushes during server
startup.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

DEFAULT_ENVIRONMENT_FILES = ("autonomous.env", "runtime.env", ".env")
DEFAULT_MANIFESTS = ("platform-requirements.json", "repair-policy.json")


@dataclass(frozen=True)
class RepositoryControlState:
    """Non-secret evidence describing the repository control initialization."""

    repository_root: str
    control_dir: str
    active: bool
    priority: int
    loaded_env_files: tuple[str, ...]
    loaded_manifests: tuple[str, ...]
    source_of_truth: str | None
    diagnostics: tuple[str, ...]


def _find_repository_root(start_dir: Path | None = None) -> Path:
    configured_root = os.getenv("AMOSCLAUD_REPOSITORY_ROOT")
    if configured_root:
        return Path(configured_root).expanduser().resolve()

    start = (start_dir or Path.cwd()).expanduser().resolve()
    for candidate in (start, *start.parents):
        if (candidate / ".amosclaud").is_dir():
            return candidate
    return start


def _safe_control_path(control_dir: Path, relative_name: str) -> Path | None:
    if not relative_name or Path(relative_name).is_absolute():
        return None
    candidate = (control_dir / relative_name).resolve()
    try:
        candidate.relative_to(control_dir.resolve())
    except ValueError:
        return None
    return candidate


def _string_list(value: Any, default: tuple[str, ...]) -> tuple[str, ...]:
    if not isinstance(value, list):
        return default
    cleaned = tuple(item.strip() for item in value if isinstance(item, str) and item.strip())
    return cleaned or default


def initialize_repository_control(
    *,
    start_dir: Path | None = None,
) -> RepositoryControlState:
    """Load ``.amosclaud`` before ordinary repository configuration.

    Existing process environment variables are never overwritten.  This keeps
    Railway, container, and operator-provided secrets authoritative while still
    giving ``.amosclaud`` precedence over the root ``.env`` file.
    """

    repository_root = _find_repository_root(start_dir)
    configured_control_dir = os.getenv("AMOSCLAUD_CONTROL_DIR", ".amosclaud")
    control_dir_path = Path(configured_control_dir).expanduser()
    control_dir = (
        control_dir_path.resolve()
        if control_dir_path.is_absolute()
        else (repository_root / control_dir_path).resolve()
    )

    if not control_dir.is_dir():
        return RepositoryControlState(
            repository_root=str(repository_root),
            control_dir=str(control_dir),
            active=False,
            priority=1000,
            loaded_env_files=(),
            loaded_manifests=(),
            source_of_truth=None,
            diagnostics=("control directory not found",),
        )

    diagnostics: list[str] = []
    loaded_manifests: list[str] = []
    startup: dict[str, Any] = {}
    startup_path = control_dir / "startup.json"
    if startup_path.is_file():
        try:
            parsed = json.loads(startup_path.read_text(encoding="utf-8"))
            if isinstance(parsed, dict):
                startup = parsed
                loaded_manifests.append(str(startup_path))
            else:
                diagnostics.append("startup.json must contain a JSON object")
        except (OSError, json.JSONDecodeError) as exc:
            diagnostics.append(f"startup.json could not be loaded: {exc}")

    priority = startup.get("priority", 0)
    if not isinstance(priority, int):
        diagnostics.append("startup priority must be an integer; using 0")
        priority = 0

    environment_files = _string_list(
        startup.get("environment_files"),
        DEFAULT_ENVIRONMENT_FILES,
    )
    manifest_names = _string_list(startup.get("manifests"), DEFAULT_MANIFESTS)

    loaded_env_files: list[str] = []
    for relative_name in environment_files:
        env_path = _safe_control_path(control_dir, relative_name)
        if env_path is None:
            diagnostics.append(f"unsafe environment path ignored: {relative_name}")
            continue
        if env_path.is_file():
            load_dotenv(env_path, override=False)
            loaded_env_files.append(str(env_path))

    source_of_truth: str | None = None
    for relative_name in manifest_names:
        manifest_path = _safe_control_path(control_dir, relative_name)
        if manifest_path is None:
            diagnostics.append(f"unsafe manifest path ignored: {relative_name}")
            continue
        if not manifest_path.is_file():
            continue
        try:
            parsed = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            diagnostics.append(f"{relative_name} could not be loaded: {exc}")
            continue
        if not isinstance(parsed, dict):
            diagnostics.append(f"{relative_name} must contain a JSON object")
            continue
        loaded_manifests.append(str(manifest_path))
        if source_of_truth is None and isinstance(parsed.get("source_of_truth"), str):
            source_of_truth = parsed["source_of_truth"]

    os.environ.setdefault("AMOSCLAUD_CONTROL_ACTIVE", "1")
    os.environ.setdefault("AMOSCLAUD_CONTROL_DIR", str(control_dir))
    if source_of_truth:
        os.environ.setdefault("AMOSCLAUD_CONTROL_SOURCE", source_of_truth)

    return RepositoryControlState(
        repository_root=str(repository_root),
        control_dir=str(control_dir),
        active=True,
        priority=priority,
        loaded_env_files=tuple(loaded_env_files),
        loaded_manifests=tuple(loaded_manifests),
        source_of_truth=source_of_truth,
        diagnostics=tuple(diagnostics),
    )

"""Folder-first workspace registry stored only on the local installation."""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,79}$")


class WorkspaceError(RuntimeError):
    """Raised when a workspace registration is invalid or unavailable."""


@dataclass(frozen=True)
class Workspace:
    id: str
    name: str
    path: str
    created_at: str


class WorkspaceRegistry:
    def __init__(self, state_dir: Path) -> None:
        self.state_dir = Path(state_dir).expanduser().resolve()
        self.registry_file = self.state_dir / "workspaces.json"
        self._lock = threading.RLock()

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _allowed_roots(self) -> tuple[Path, ...]:
        configured = os.getenv("AMOSCLAUD_LOCAL_ALLOWED_ROOTS", "").strip()
        if not configured:
            return (Path.home().resolve(),)
        roots: list[Path] = []
        for value in configured.split(os.pathsep):
            if value.strip():
                roots.append(Path(value.strip()).expanduser().resolve())
        return tuple(dict.fromkeys(roots))

    def _validate_path(self, value: str) -> Path:
        raw = str(value or "").strip()
        if not raw or "\x00" in raw:
            raise WorkspaceError("Workspace path is invalid")
        candidate = Path(raw).expanduser().resolve(strict=True)
        if not candidate.is_dir():
            raise WorkspaceError("Workspace path must be an existing directory")
        allowed_roots = self._allowed_roots()
        if allowed_roots and not any(
            candidate == root or candidate.is_relative_to(root) for root in allowed_roots
        ):
            raise WorkspaceError("Workspace path is outside AMOSCLAUD_LOCAL_ALLOWED_ROOTS")
        return candidate

    def _read(self) -> list[dict[str, Any]]:
        try:
            data = json.loads(self.registry_file.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except (OSError, json.JSONDecodeError) as exc:
            raise WorkspaceError("Workspace registry is unreadable") from exc
        if not isinstance(data, list):
            raise WorkspaceError("Workspace registry has an invalid format")
        return [item for item in data if isinstance(item, dict)]

    def _write(self, records: list[dict[str, Any]]) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.state_dir, 0o700)
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=self.state_dir,
            delete=False,
            prefix="workspaces-",
            suffix=".tmp",
        ) as handle:
            json.dump(records, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
            temp_path = Path(handle.name)
        os.chmod(temp_path, 0o600)
        temp_path.replace(self.registry_file)
        os.chmod(self.registry_file, 0o600)

    @staticmethod
    def _from_record(item: dict[str, Any]) -> Workspace:
        return Workspace(
            id=str(item["id"]),
            name=str(item["name"]),
            path=str(item["path"]),
            created_at=str(item["created_at"]),
        )

    def list(self) -> list[Workspace]:
        with self._lock:
            return [self._from_record(item) for item in self._read()]

    def get(self, workspace_id: str) -> Workspace:
        for workspace in self.list():
            if workspace.id == workspace_id:
                return workspace
        raise WorkspaceError("Workspace was not found")

    def register(self, *, name: str, path: str) -> Workspace:
        cleaned_name = str(name or "").strip()
        if not _NAME_PATTERN.fullmatch(cleaned_name):
            raise WorkspaceError("Workspace name contains unsupported characters")
        candidate = self._validate_path(path)
        with self._lock:
            records = self._read()
            canonical = str(candidate)
            for item in records:
                if str(item.get("path")) == canonical:
                    return self._from_record(item)
            workspace = Workspace(
                id=f"ws_{uuid.uuid4().hex}",
                name=cleaned_name,
                path=canonical,
                created_at=self._utc_now(),
            )
            records.append(asdict(workspace))
            self._write(records)
            return workspace

    def remove(self, workspace_id: str) -> None:
        with self._lock:
            records = self._read()
            kept = [item for item in records if str(item.get("id")) != workspace_id]
            if len(kept) == len(records):
                raise WorkspaceError("Workspace was not found")
            self._write(kept)

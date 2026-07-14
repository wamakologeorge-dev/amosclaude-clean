from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,119}$")
WORKSPACE_DIRS = (
    "projects",
    "notes",
    "tasks",
    "agents",
    "knowledge",
    "automations",
    "logs",
    "backups",
)


class WorkspaceError(RuntimeError):
    pass


def _default_workspace_root() -> Path:
    configured = os.getenv("AMOSCLAUD_WORKSPACE")
    if configured:
        return Path(configured)
    auth_db = Path(os.getenv("AUTH_DB_PATH", "data/auth.db"))
    return auth_db.parent / "workspace"


class WorkspaceEngine:
    """Folder-first source of truth for Amosclaud-owned content."""

    def __init__(self, root: Path | None = None):
        self.root = (root or _default_workspace_root()).resolve()
        self.initialize()

    def initialize(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        for name in WORKSPACE_DIRS:
            (self.root / name).mkdir(parents=True, exist_ok=True)
        manifest = self.root / "workspace.yaml"
        if not manifest.exists():
            self._atomic_write_yaml(
                manifest,
                {
                    "name": "Amosclaud Workspace",
                    "format": 1,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "source_of_truth": "files",
                },
            )

    def _safe_path(self, relative: str, *, must_exist: bool = False) -> Path:
        relative = relative.replace("\\", "/").strip("/")
        if not relative or relative.startswith(".") or ".." in Path(relative).parts:
            raise WorkspaceError("Invalid workspace path")
        candidate = (self.root / relative).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise WorkspaceError("Workspace path escapes the configured root")
        if must_exist and not candidate.exists():
            raise WorkspaceError("Workspace item not found")
        return candidate

    @staticmethod
    def _validate_name(name: str) -> str:
        normalized = name.strip()
        if not SAFE_NAME.fullmatch(normalized):
            raise WorkspaceError("Name contains unsupported characters")
        return normalized

    @staticmethod
    def _atomic_write_text(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(path)

    def _atomic_write_yaml(self, path: Path, value: dict[str, Any]) -> None:
        self._atomic_write_text(path, yaml.safe_dump(value, sort_keys=False, allow_unicode=True))

    def manifest(self) -> dict[str, Any]:
        value = yaml.safe_load((self.root / "workspace.yaml").read_text(encoding="utf-8")) or {}
        return value if isinstance(value, dict) else {}

    def summary(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "manifest": self.manifest(),
            "counts": {
                directory: sum(1 for item in (self.root / directory).rglob("*") if item.is_file())
                for directory in WORKSPACE_DIRS
            },
        }

    def list_items(self, section: str) -> list[dict[str, Any]]:
        if section not in WORKSPACE_DIRS:
            raise WorkspaceError("Unknown workspace section")
        base = self.root / section
        items: list[dict[str, Any]] = []
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.name.endswith(".tmp"):
                continue
            stat = path.stat()
            items.append(
                {
                    "path": path.relative_to(self.root).as_posix(),
                    "name": path.name,
                    "size": stat.st_size,
                    "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                    "kind": path.suffix.lower().lstrip(".") or "text",
                }
            )
        return items

    def read_item(self, relative: str) -> dict[str, Any]:
        path = self._safe_path(relative, must_exist=True)
        if not path.is_file():
            raise WorkspaceError("Workspace item is not a file")
        if path.stat().st_size > 2 * 1024 * 1024:
            raise WorkspaceError("Workspace item is too large to open in the dashboard")
        content = path.read_text(encoding="utf-8")
        parsed: Any = None
        if path.suffix.lower() in {".yaml", ".yml"}:
            parsed = yaml.safe_load(content)
        elif path.suffix.lower() == ".json":
            parsed = json.loads(content)
        return {
            "path": path.relative_to(self.root).as_posix(),
            "content": content,
            "parsed": parsed,
        }

    def create_note(self, title: str, content: str, tags: list[str] | None = None) -> dict[str, Any]:
        safe_title = self._validate_name(title)
        slug = re.sub(r"[^a-z0-9]+", "-", safe_title.lower()).strip("-")
        path = self._safe_path(f"notes/{slug}.md")
        if path.exists():
            raise WorkspaceError("A note with this title already exists")
        frontmatter = yaml.safe_dump({"title": safe_title, "tags": tags or []}, sort_keys=False).strip()
        self._atomic_write_text(path, f"---\n{frontmatter}\n---\n\n{content.rstrip()}\n")
        return self.read_item(path.relative_to(self.root).as_posix())

    def create_task(self, title: str, project: str | None = None, assigned_to: str | None = None) -> dict[str, Any]:
        safe_title = self._validate_name(title)
        slug = re.sub(r"[^a-z0-9]+", "-", safe_title.lower()).strip("-")
        path = self._safe_path(f"tasks/{slug}.yaml")
        if path.exists():
            raise WorkspaceError("A task with this title already exists")
        value = {
            "title": safe_title,
            "status": "pending",
            "project": project,
            "assigned_to": assigned_to,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self._atomic_write_yaml(path, value)
        return self.read_item(path.relative_to(self.root).as_posix())

    def create_project(self, name: str, description: str = "") -> dict[str, Any]:
        safe_name = self._validate_name(name)
        slug = re.sub(r"[^a-z0-9]+", "-", safe_name.lower()).strip("-")
        project_dir = self._safe_path(f"projects/{slug}")
        if project_dir.exists():
            raise WorkspaceError("A project with this name already exists")
        project_dir.mkdir(parents=True)
        self._atomic_write_yaml(
            project_dir / "project.yaml",
            {
                "name": safe_name,
                "description": description,
                "status": "active",
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        self._atomic_write_text(project_dir / "README.md", f"# {safe_name}\n\n{description.rstrip()}\n")
        (project_dir / "files").mkdir()
        (project_dir / "tasks").mkdir()
        return {
            "path": project_dir.relative_to(self.root).as_posix(),
            "manifest": yaml.safe_load((project_dir / "project.yaml").read_text(encoding="utf-8")),
        }

    def append_activity(self, event: dict[str, Any]) -> None:
        path = self.root / "logs" / "activity.jsonl"
        payload = {"timestamp": datetime.now(timezone.utc).isoformat(), **event}
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, ensure_ascii=False) + "\n")

"""Authoritative connector between Amosclaud services and native Git storage."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select

from database.models import Repository, UserProfile
from database.session import create_database, session_scope


class RepositoryConnectorError(RuntimeError):
    """Raised when repository identity, storage, or workspace operations fail."""


@dataclass(frozen=True, slots=True)
class RepositoryRecord:
    id: int
    owner: str
    owner_email: str
    name: str
    default_branch: str
    is_private: bool
    storage_path: Path


class RepositoryConnector:
    """Resolve database repositories into confined native Git storage paths.

    All platform components should use this connector instead of constructing
    repository paths independently. The shared SQLAlchemy database is the source
    of truth; filesystem directories never create repository identity by
    themselves.
    """

    def __init__(self, root: str | Path | None = None) -> None:
        configured = os.getenv("AMOSCLAUD_REPOSITORIES_ROOT", "").strip()
        self.root = Path(root or configured or "./data/repositories").expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        create_database()

    @staticmethod
    def _safe_segment(value: str, field: str) -> str:
        candidate = value.strip()
        if not candidate or not all(ch.isalnum() or ch in "-_" for ch in candidate):
            raise RepositoryConnectorError(f"invalid {field}")
        return candidate

    def storage_path(self, owner: str, name: str) -> Path:
        safe_owner = self._safe_segment(owner, "repository owner")
        safe_name = self._safe_segment(name.removesuffix(".git"), "repository name")
        candidate = (self.root / safe_owner / f"{safe_name}.git").resolve(strict=False)
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise RepositoryConnectorError("repository path escapes storage root") from exc
        return candidate

    def resolve(self, owner: str, name: str) -> RepositoryRecord:
        safe_owner = self._safe_segment(owner, "repository owner")
        safe_name = self._safe_segment(name.removesuffix(".git"), "repository name")
        with session_scope() as session:
            row = session.scalar(
                select(Repository)
                .join(UserProfile, Repository.owner_id == UserProfile.id)
                .where(UserProfile.username == safe_owner, Repository.name == safe_name)
            )
            if row is None:
                raise RepositoryConnectorError("repository not found")
            canonical = self.storage_path(safe_owner, safe_name)
            configured = Path(row.storage_path).expanduser().resolve() if row.storage_path else canonical
            try:
                configured.relative_to(self.root)
            except ValueError as exc:
                raise RepositoryConnectorError("database storage path escapes repository root") from exc
            if row.storage_path != str(configured):
                row.storage_path = str(configured)
            return RepositoryRecord(
                id=int(row.id),
                owner=safe_owner,
                owner_email=str(row.owner.email),
                name=safe_name,
                default_branch=str(row.default_branch or "main"),
                is_private=bool(row.is_private),
                storage_path=configured,
            )

    def initialize(self, repository_id: int) -> RepositoryRecord:
        with session_scope() as session:
            row = session.get(Repository, repository_id)
            if row is None:
                raise RepositoryConnectorError("repository not found")
            owner = str(row.owner.username)
            name = str(row.name)
        record = self.resolve(owner, name)
        record.storage_path.parent.mkdir(parents=True, exist_ok=True)
        if record.storage_path.exists():
            if not (record.storage_path / "HEAD").exists():
                raise RepositoryConnectorError("repository storage exists but is not a bare Git repository")
            return record
        subprocess.run(
            ["git", "init", "--bare", f"--initial-branch={record.default_branch}", str(record.storage_path)],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return record

    def require_existing(self, owner: str, name: str) -> RepositoryRecord:
        record = self.resolve(owner, name)
        if not record.storage_path.is_dir() or not (record.storage_path / "HEAD").exists():
            raise RepositoryConnectorError("repository storage is not initialized")
        return record

    def create_worktree(self, repository_id: int, branch: str, *, base: str | None = None) -> Path:
        """Create an isolated temporary clone for an Agent or fixer task."""
        record = self.initialize(repository_id)
        safe_branch = self._safe_segment(branch.replace("/", "-"), "branch")
        workspace = Path(tempfile.mkdtemp(prefix=f"amosclaud-{repository_id}-"))
        try:
            subprocess.run(
                ["git", "clone", "--no-checkout", str(record.storage_path), str(workspace)],
                check=True,
                capture_output=True,
                text=True,
                timeout=60,
            )
            start = base or record.default_branch
            exists = subprocess.run(
                ["git", "-C", str(workspace), "rev-parse", "--verify", start],
                capture_output=True,
                text=True,
                timeout=15,
            ).returncode == 0
            command = ["git", "-C", str(workspace), "checkout", "-B", safe_branch]
            if exists:
                command.append(start)
            subprocess.run(command, check=True, capture_output=True, text=True, timeout=30)
            return workspace
        except Exception:
            shutil.rmtree(workspace, ignore_errors=True)
            raise

    @staticmethod
    def remove_workspace(path: str | Path) -> None:
        shutil.rmtree(Path(path), ignore_errors=True)

"""Authoritative connector between Amosclaud services and native Git storage."""
from __future__ import annotations

import os
import shutil
import sqlite3
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
    """Resolve every Amosclaud repository through one database/storage contract.

    The shared SQLAlchemy database is authoritative for Agent jobs, CI and pull
    requests. Existing repositories from the original native SQLite API are
    mirrored lazily so they remain available while the platform migrates.
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

    def _mirror_legacy(self, owner: str, name: str) -> None:
        """Mirror an original auth-database repository into the shared database."""
        from amoscloud_ai.api.routes.auth import DB_PATH

        if not DB_PATH.exists():
            return
        db = sqlite3.connect(DB_PATH)
        db.row_factory = sqlite3.Row
        try:
            tables = {
                row[0]
                for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            }
            if not {"users", "repositories"}.issubset(tables):
                return
            row = db.execute(
                """SELECT r.id,r.name,r.description,r.visibility,r.default_branch,
                          u.name AS owner_name,u.email AS owner_email
                     FROM repositories r JOIN users u ON u.id=r.owner_id
                    WHERE lower(u.name)=lower(?) AND lower(r.name)=lower(?)""",
                (owner, name),
            ).fetchone()
            if row is None:
                return
            legacy_root = Path(os.getenv("REPOSITORY_STORAGE_PATH", "data/repositories")).resolve()
            legacy_path = (legacy_root / str(row["id"])).resolve(strict=False)
            try:
                legacy_path.relative_to(legacy_root)
            except ValueError as exc:
                raise RepositoryConnectorError("legacy repository path escapes storage root") from exc
            with session_scope() as session:
                profile = session.scalar(select(UserProfile).where(UserProfile.email == row["owner_email"]))
                if profile is None:
                    username = self._safe_segment(str(row["owner_name"]), "repository owner")
                    existing = session.scalar(select(UserProfile).where(UserProfile.username == username))
                    if existing is not None:
                        username = f"{username}-{row['id']}"
                    profile = UserProfile(username=username, email=str(row["owner_email"]))
                    session.add(profile)
                    session.flush()
                repository = session.scalar(
                    select(Repository).where(
                        Repository.owner_id == profile.id,
                        Repository.name == str(row["name"]),
                    )
                )
                if repository is None:
                    repository = Repository(
                        owner_id=profile.id,
                        name=str(row["name"]),
                        description=str(row["description"] or ""),
                        is_private=str(row["visibility"]) != "public",
                        default_branch=str(row["default_branch"] or "main"),
                        storage_path=str(legacy_path),
                    )
                    session.add(repository)
        finally:
            db.close()

    def resolve(self, owner: str, name: str) -> RepositoryRecord:
        safe_owner = self._safe_segment(owner, "repository owner")
        safe_name = self._safe_segment(name.removesuffix(".git"), "repository name")

        def lookup() -> Repository | None:
            with session_scope() as session:
                return session.scalar(
                    select(Repository)
                    .join(UserProfile, Repository.owner_id == UserProfile.id)
                    .where(UserProfile.username == safe_owner, Repository.name == safe_name)
                )

        row = lookup()
        if row is None:
            self._mirror_legacy(safe_owner, safe_name)
            row = lookup()
        if row is None:
            raise RepositoryConnectorError("repository not found")

        with session_scope() as session:
            current = session.get(Repository, int(row.id))
            if current is None:
                raise RepositoryConnectorError("repository not found")
            canonical = self.storage_path(safe_owner, safe_name)
            configured = Path(current.storage_path).expanduser().resolve() if current.storage_path else canonical
            allowed_roots = {self.root, Path(os.getenv("REPOSITORY_STORAGE_PATH", "data/repositories")).resolve()}
            if not any(_is_within(configured, allowed) for allowed in allowed_roots):
                raise RepositoryConnectorError("database storage path escapes repository roots")
            if current.storage_path != str(configured):
                current.storage_path = str(configured)
            return RepositoryRecord(
                id=int(current.id),
                owner=str(current.owner.username),
                owner_email=str(current.owner.email),
                name=str(current.name),
                default_branch=str(current.default_branch or "main"),
                is_private=bool(current.is_private),
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
            if not _is_git_repository(record.storage_path):
                raise RepositoryConnectorError("repository storage exists but is not a Git repository")
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
        if not record.storage_path.is_dir() or not _is_git_repository(record.storage_path):
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


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _is_git_repository(path: Path) -> bool:
    return (path / "HEAD").exists() or (path / ".git" / "HEAD").exists()

"""Persistent active-project context for Amosclaud OS."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from fastapi import HTTPException
from pydantic import BaseModel, Field

from amoscloud_ai.api.routes.auth import DB_PATH


class ProjectContextSelection(BaseModel):
    repository_id: int = Field(..., ge=1)
    workspace_id: str | None = Field(default=None, max_length=128)
    branch: str | None = Field(default=None, min_length=1, max_length=200)


class ProjectContextState(BaseModel):
    active: bool
    user_id: int
    repository_id: int | None = None
    repository_name: str | None = None
    workspace_id: str | None = None
    branch: str | None = None
    role: str | None = None
    owner_authorized: bool = False
    provider: str = "native"
    updated_at: str | None = None

    def as_agent_metadata(self) -> dict[str, object]:
        return {
            "project_context_source": "amosclaud-os",
            "repository_id": self.repository_id,
            "selected_repository": self.repository_name,
            "workspace_id": self.workspace_id,
            "selected_workspace": self.workspace_id,
            "branch": self.branch,
            "repository_role": self.role,
            "owner_authorized": self.owner_authorized,
            "owner_authorization": "session-owner" if self.owner_authorized else self.role,
            "repository_provider": self.provider,
        }


class ProjectContextService:
    def __init__(self, database_path=DB_PATH):
        self.database_path = database_path

    def _connect(self) -> sqlite3.Connection:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.database_path)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        db.execute(
            """CREATE TABLE IF NOT EXISTS project_contexts (
                   user_id INTEGER PRIMARY KEY,
                   repository_id INTEGER NOT NULL,
                   workspace_id TEXT,
                   branch TEXT NOT NULL,
                   provider TEXT NOT NULL DEFAULT 'native',
                   updated_at TEXT NOT NULL,
                   FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                   FOREIGN KEY(repository_id) REFERENCES repositories(id) ON DELETE CASCADE
               )"""
        )
        db.commit()
        return db

    @staticmethod
    def _repository(db: sqlite3.Connection, repository_id: int, user_id: int) -> sqlite3.Row:
        try:
            row = db.execute(
                """SELECT r.id,r.name,r.default_branch,
                          CASE WHEN r.owner_id=? THEN 'owner' ELSE c.role END AS role
                   FROM repositories r
                   LEFT JOIN repository_collaborators c
                     ON c.repository_id=r.id AND c.user_id=?
                   WHERE r.id=? AND (r.owner_id=? OR c.user_id=? OR r.visibility='public')""",
                (user_id, user_id, repository_id, user_id, user_id),
            ).fetchone()
        except sqlite3.OperationalError as exc:
            raise HTTPException(status_code=409, detail="Repository service is not initialized") from exc
        if not row:
            raise HTTPException(status_code=404, detail="Repository not found")
        return row

    def _state(
        self,
        db: sqlite3.Connection,
        user_id: int,
        repository_id: int,
        workspace_id: str | None,
        branch: str | None,
        provider: str = "native",
        updated_at: str | None = None,
    ) -> ProjectContextState:
        repository = self._repository(db, repository_id, user_id)
        workspace = None
        if workspace_id:
            try:
                workspace = db.execute(
                    """SELECT id,branch FROM workspaces
                       WHERE id=? AND repository_id=? AND user_id=? AND status!='deleted'""",
                    (workspace_id, repository_id, user_id),
                ).fetchone()
            except sqlite3.OperationalError:
                workspace = None
            if not workspace:
                raise HTTPException(status_code=404, detail="Workspace not found for this repository")
        resolved_branch = branch or (workspace["branch"] if workspace else None) or repository["default_branch"] or "main"
        role = repository["role"] or "viewer"
        return ProjectContextState(
            active=True,
            user_id=user_id,
            repository_id=repository_id,
            repository_name=repository["name"],
            workspace_id=workspace_id,
            branch=resolved_branch,
            role=role,
            owner_authorized=role == "owner",
            provider=provider,
            updated_at=updated_at or datetime.now(timezone.utc).isoformat(),
        )

    @staticmethod
    def _save(db: sqlite3.Connection, state: ProjectContextState) -> None:
        db.execute(
            """INSERT INTO project_contexts(user_id,repository_id,workspace_id,branch,provider,updated_at)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(user_id) DO UPDATE SET
                   repository_id=excluded.repository_id,
                   workspace_id=excluded.workspace_id,
                   branch=excluded.branch,
                   provider=excluded.provider,
                   updated_at=excluded.updated_at""",
            (state.user_id, state.repository_id, state.workspace_id, state.branch, state.provider, state.updated_at),
        )
        db.commit()

    def select(self, user_id: int, selection: ProjectContextSelection) -> ProjectContextState:
        with self._connect() as db:
            state = self._state(db, user_id, selection.repository_id, selection.workspace_id, selection.branch)
            self._save(db, state)
            return state

    def resolve(self, user_id: int) -> ProjectContextState:
        with self._connect() as db:
            saved = db.execute("SELECT * FROM project_contexts WHERE user_id=?", (user_id,)).fetchone()
            if saved:
                try:
                    return self._state(db, user_id, saved["repository_id"], saved["workspace_id"], saved["branch"], saved["provider"], saved["updated_at"])
                except HTTPException:
                    db.execute("DELETE FROM project_contexts WHERE user_id=?", (user_id,))
                    db.commit()
            try:
                workspace = db.execute(
                    "SELECT id,repository_id,branch FROM workspaces WHERE user_id=? AND status!='deleted' ORDER BY updated_at DESC LIMIT 1",
                    (user_id,),
                ).fetchone()
            except sqlite3.OperationalError:
                workspace = None
            if workspace:
                state = self._state(db, user_id, workspace["repository_id"], workspace["id"], workspace["branch"])
                self._save(db, state)
                return state
            try:
                repository = db.execute(
                    """SELECT r.id FROM repositories r
                       LEFT JOIN repository_collaborators c ON c.repository_id=r.id AND c.user_id=?
                       WHERE r.owner_id=? OR c.user_id=?
                       ORDER BY r.updated_at DESC LIMIT 1""",
                    (user_id, user_id, user_id),
                ).fetchone()
            except sqlite3.OperationalError:
                repository = None
            if repository:
                state = self._state(db, user_id, repository["id"], None, None)
                self._save(db, state)
                return state
        return ProjectContextState(active=False, user_id=user_id)

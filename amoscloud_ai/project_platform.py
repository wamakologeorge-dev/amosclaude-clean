"""Persistent project, issue, and verified-result APIs for Amosclaud.com."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import Cookie, Header, HTTPException
from pydantic import BaseModel, Field

from amoscloud_ai.api.routes import task_router


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_schema(db) -> None:
    task_router._ensure_schema(db)
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS platform_projects (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            repository TEXT,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS platform_issues (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            body TEXT NOT NULL DEFAULT '',
            labels_json TEXT NOT NULL DEFAULT '[]',
            state TEXT NOT NULL DEFAULT 'open',
            task_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(project_id) REFERENCES platform_projects(id) ON DELETE CASCADE,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(task_id) REFERENCES global_tasks(id)
        );
        CREATE INDEX IF NOT EXISTS idx_platform_projects_user ON platform_projects(user_id, updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_platform_issues_project ON platform_issues(project_id, created_at DESC);
        """
    )
    db.commit()


class ProjectCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    description: str = Field(default="", max_length=10_000)
    repository: str | None = Field(default=None, max_length=300)


class IssueCreate(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    body: str = Field(default="", max_length=50_000)
    labels: list[str] = Field(default_factory=list, max_length=20)
    start_work: bool = False
    mode: Literal["build", "fix", "test", "review", "deploy"] = "fix"
    require_approval: bool = True


def _actor(session: str | None, authorization: str | None) -> int:
    return task_router._actor(session, authorization)


def _owned_project(db, project_id: str, user_id: int):
    row = db.execute(
        "SELECT * FROM platform_projects WHERE id=? AND user_id=?", (project_id, user_id)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Project not found")
    return row


def _project_dict(row) -> dict[str, Any]:
    return dict(row)


def _issue_dict(row) -> dict[str, Any]:
    item = dict(row)
    item["labels"] = json.loads(item.pop("labels_json") or "[]")
    return item


def register_project_routes() -> None:
    router = task_router.router
    if any(getattr(route, "path", "") == "/projects" for route in router.routes):
        return

    @router.post("/projects", status_code=201, tags=["projects"])
    def create_project(
        body: ProjectCreate,
        amos_session: str | None = Cookie(default=None),
        authorization: str | None = Header(default=None),
    ) -> dict:
        user_id = _actor(amos_session, authorization)
        project_id = "project_" + uuid.uuid4().hex
        now = _now()
        with task_router._connect() as db:
            _ensure_schema(db)
            db.execute(
                "INSERT INTO platform_projects(id,user_id,name,description,repository,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
                (project_id, user_id, body.name.strip(), body.description, body.repository, now, now),
            )
            db.commit()
            return _project_dict(db.execute("SELECT * FROM platform_projects WHERE id=?", (project_id,)).fetchone())

    @router.get("/projects", tags=["projects"])
    def list_projects(
        amos_session: str | None = Cookie(default=None),
        authorization: str | None = Header(default=None),
    ) -> list[dict]:
        user_id = _actor(amos_session, authorization)
        with task_router._connect() as db:
            _ensure_schema(db)
            rows = db.execute(
                "SELECT * FROM platform_projects WHERE user_id=? ORDER BY updated_at DESC", (user_id,)
            ).fetchall()
            return [_project_dict(row) for row in rows]

    @router.get("/projects/{project_id}", tags=["projects"])
    def get_project(
        project_id: str,
        amos_session: str | None = Cookie(default=None),
        authorization: str | None = Header(default=None),
    ) -> dict:
        user_id = _actor(amos_session, authorization)
        with task_router._connect() as db:
            _ensure_schema(db)
            project = _owned_project(db, project_id, user_id)
            issues = db.execute(
                "SELECT * FROM platform_issues WHERE project_id=? ORDER BY created_at DESC", (project_id,)
            ).fetchall()
            tasks = db.execute(
                "SELECT * FROM global_tasks WHERE user_id=? AND json_extract(metadata_json, '$.project_id')=? ORDER BY created_at DESC",
                (user_id, project_id),
            ).fetchall()
            result = _project_dict(project)
            result["issues"] = [_issue_dict(row) for row in issues]
            result["tasks"] = [task_router._task_dict(row) for row in tasks]
            return result

    @router.post("/projects/{project_id}/issues", status_code=201, tags=["projects"])
    def create_project_issue(
        project_id: str,
        body: IssueCreate,
        amos_session: str | None = Cookie(default=None),
        authorization: str | None = Header(default=None),
    ) -> dict:
        user_id = _actor(amos_session, authorization)
        issue_id = "issue_" + uuid.uuid4().hex
        now = _now()
        with task_router._connect() as db:
            _ensure_schema(db)
            project = _owned_project(db, project_id, user_id)
            task_id = None
            if body.start_work:
                objective = f"Issue: {body.title.strip()}\n\n{body.body.strip()}"
                task = task_router.create_task(
                    task_router.TaskCreate(
                        objective=objective,
                        repository=project["repository"],
                        mode=body.mode,
                        delivery="pull_request",
                        execution_target="github" if project["repository"] else "cloud",
                        require_approval=body.require_approval,
                        metadata={
                            "operator": "Amosclaud-bot",
                            "single_brain": True,
                            "source": "amosclaud-project-issue",
                            "project_id": project_id,
                            "issue_id": issue_id,
                        },
                    ),
                    amos_session=amos_session,
                    authorization=authorization,
                )
                task_id = task["id"]
            db.execute(
                "INSERT INTO platform_issues(id,project_id,user_id,title,body,labels_json,state,task_id,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (issue_id, project_id, user_id, body.title.strip(), body.body, json.dumps(body.labels), "open", task_id, now, now),
            )
            db.execute("UPDATE platform_projects SET updated_at=? WHERE id=?", (now, project_id))
            db.commit()
            return _issue_dict(db.execute("SELECT * FROM platform_issues WHERE id=?", (issue_id,)).fetchone())

    @router.get("/projects/{project_id}/results", tags=["projects"])
    def project_results(
        project_id: str,
        amos_session: str | None = Cookie(default=None),
        authorization: str | None = Header(default=None),
    ) -> list[dict]:
        user_id = _actor(amos_session, authorization)
        with task_router._connect() as db:
            _ensure_schema(db)
            _owned_project(db, project_id, user_id)
            rows = db.execute(
                "SELECT * FROM global_tasks WHERE user_id=? AND json_extract(metadata_json, '$.project_id')=? AND status IN ('completed','failed') ORDER BY finished_at DESC",
                (user_id, project_id),
            ).fetchall()
            return [task_router._task_dict(row) for row in rows]


register_project_routes()

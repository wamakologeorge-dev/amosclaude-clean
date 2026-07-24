from __future__ import annotations

import sqlite3

from amoscloud_ai.api.routes import auth as auth_routes
from amoscloud_ai.api.routes import repositories
from amosclaud_os.agent.executor import execute_native_operation


def _prepare_user_database(path) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA foreign_keys = ON")
        db.execute(
            """CREATE TABLE users (
                   id INTEGER PRIMARY KEY,
                   name TEXT NOT NULL,
                   email TEXT NOT NULL UNIQUE,
                   is_admin INTEGER NOT NULL DEFAULT 0
               )"""
        )
        db.execute(
            "INSERT INTO users(id,name,email,is_admin) VALUES (1,'George','george@example.com',1)"
        )
        db.commit()
    return {"id": 1, "name": "George", "email": "george@example.com", "is_admin": 1}


def test_native_executor_creates_repository_and_issue(tmp_path, monkeypatch) -> None:
    database = tmp_path / "amosclaud.db"
    repository_root = tmp_path / "repositories"
    user = _prepare_user_database(database)
    monkeypatch.setattr(auth_routes, "DB_PATH", database)
    monkeypatch.setattr(repositories, "DB_PATH", database)
    monkeypatch.setattr(repositories, "REPOSITORY_ROOT", repository_root)

    created = execute_native_operation(
        user=user,
        objective="Create a repository named real-platform",
        mode="build",
        metadata={"operation": "create_repository", "new_repository_name": "real-platform"},
    )

    assert created is not None and created.succeeded
    assert created.resource["name"] == "real-platform"
    repository_id = int(created.resource["id"])
    assert (repository_root / str(repository_id) / ".git").is_dir()
    assert (repository_root / str(repository_id) / "README.md").is_file()

    issue = execute_native_operation(
        user=user,
        objective="Create an issue for the login failure",
        mode="build",
        metadata={
            "operation": "create_issue",
            "repository_id": repository_id,
            "issue_title": "Login failure",
            "issue_description": "Users receive an error after submitting the login form.",
        },
    )

    assert issue is not None and issue.succeeded
    assert issue.resource["number"] == 1
    assert issue.resource["title"] == "Login failure"
    with sqlite3.connect(database) as db:
        row = db.execute(
            "SELECT title,state FROM repository_issues WHERE repository_id=? AND number=1",
            (repository_id,),
        ).fetchone()
    assert row == ("Login failure", "open")


def test_native_executor_never_uses_platform_source_as_missing_repository_fallback(
    tmp_path, monkeypatch
) -> None:
    database = tmp_path / "amosclaud.db"
    user = _prepare_user_database(database)
    monkeypatch.setattr(auth_routes, "DB_PATH", database)
    monkeypatch.setattr(repositories, "DB_PATH", database)
    monkeypatch.setattr(repositories, "REPOSITORY_ROOT", tmp_path / "repositories")

    result = execute_native_operation(
        user=user,
        objective="Fix the application and verify it",
        mode="fix",
        metadata={"use_agent": True, "apply_changes": True},
    )

    assert result is not None
    assert result.status == "failed"
    assert "No native Amosclaud repository is selected" in result.summary
    assert any("did not run against its own application source" in item for item in result.evidence)


def test_browser_routes_actions_to_native_executor() -> None:
    source = open("web/unified-agent-runtime.js", encoding="utf-8").read()
    assert "/api/v1/core/os/execute" in source
    assert "native-or-truthful-blocker" in source
    assert "Execute this action now" in source
    assert "planner: 'codex-style'" not in source

import sqlite3
from pathlib import Path

from amoscloud_ai import github_repository_sync
from amoscloud_ai.api.routes import github_repositories, repositories


def _point_repository_database(monkeypatch, database: Path) -> None:
    monkeypatch.setattr(repositories, "DB_PATH", database)
    monkeypatch.setattr(github_repositories, "DB_PATH", database)


def test_sync_schema_initializes_a_blank_database(tmp_path: Path, monkeypatch) -> None:
    database = tmp_path / "blank-auth.db"
    _point_repository_database(monkeypatch, database)

    github_repository_sync.ensure_sync_columns()

    with sqlite3.connect(database) as db:
        tables = {
            row[0]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        columns = {
            row[1]
            for row in db.execute("PRAGMA table_info(repositories)").fetchall()
        }

    assert "repositories" in tables
    assert "github_connections" in tables
    assert {
        "id",
        "owner_id",
        "name",
        "description",
        "visibility",
        "default_branch",
        "created_at",
        "updated_at",
        "github_full_name",
        "github_html_url",
        "github_default_branch",
        "github_last_sync_at",
        "github_sync_state",
        "github_sync_detail",
        "github_last_remote_sha",
    }.issubset(columns)


def test_background_sync_contains_unexpected_failures(monkeypatch) -> None:
    def fail(*_args, **_kwargs):
        raise sqlite3.OperationalError("no such table: repositories")

    monkeypatch.setattr(github_repository_sync, "_synchronize_github_push", fail)

    result = github_repository_sync.synchronize_github_push(
        "example/project",
        "refs/heads/main",
        "abc123",
    )

    assert result == [
        {
            "repository_id": None,
            "state": "error",
            "detail": "Automatic GitHub pull failed: OperationalError",
        }
    ]

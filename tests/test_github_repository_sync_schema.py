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
        "github_last_sync_attempt_at",
        "github_sync_state",
        "github_sync_detail",
        "github_last_remote_sha",
        "github_repository_id",
    }.issubset(columns)


def test_success_and_failure_timestamps_are_separate(tmp_path: Path, monkeypatch) -> None:
    database = tmp_path / "timestamps.db"
    _point_repository_database(monkeypatch, database)
    github_repository_sync.ensure_sync_columns()
    with sqlite3.connect(database) as db:
        db.execute(
            """INSERT INTO repositories
               (id,owner_id,name,description,visibility,default_branch,created_at,updated_at)
               VALUES (1,1,'project','','private','main','created','updated')"""
        )
        db.commit()

    github_repository_sync._record(1, "synced", "first success", "abc", successful=True)
    with sqlite3.connect(database) as db:
        first = db.execute(
            """SELECT github_last_sync_at,github_last_sync_attempt_at
               FROM repositories WHERE id=1"""
        ).fetchone()
    assert first[0]
    assert first[1]

    github_repository_sync._record(1, "conflict", "dirty", "def")
    with sqlite3.connect(database) as db:
        second = db.execute(
            """SELECT github_last_sync_at,github_last_sync_attempt_at,
                      github_sync_state,github_last_remote_sha
               FROM repositories WHERE id=1"""
        ).fetchone()
    assert second[0] == first[0]
    assert second[1] >= first[1]
    assert second[2] == "conflict"
    assert second[3] == "def"


def test_repository_mapping_prefers_immutable_id_and_updates_name(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database = tmp_path / "rename.db"
    _point_repository_database(monkeypatch, database)
    github_repository_sync.ensure_sync_columns()
    with sqlite3.connect(database) as db:
        db.execute(
            """INSERT INTO repositories
               (id,owner_id,name,description,visibility,default_branch,created_at,updated_at,
                github_full_name,github_default_branch,github_repository_id)
               VALUES (1,1,'project','','private','main','created','updated',
                       'OldOwner/OldName','main',9988)"""
        )
        db.commit()

    rows = github_repository_sync._mapped_rows("NewOwner/NewName", 9988)
    assert [row["id"] for row in rows] == [1]
    github_repository_sync._refresh_mapping(1, "NewOwner/NewName", 9988)
    with sqlite3.connect(database) as db:
        mapped = db.execute(
            "SELECT github_full_name,github_repository_id FROM repositories WHERE id=1"
        ).fetchone()
    assert mapped == ("NewOwner/NewName", 9988)


def test_repository_name_fallback_is_case_insensitive(tmp_path: Path, monkeypatch) -> None:
    database = tmp_path / "case.db"
    _point_repository_database(monkeypatch, database)
    github_repository_sync.ensure_sync_columns()
    with sqlite3.connect(database) as db:
        db.execute(
            """INSERT INTO repositories
               (id,owner_id,name,description,visibility,default_branch,created_at,updated_at,
                github_full_name,github_default_branch)
               VALUES (1,1,'project','','private','main','created','updated',
                       'Owner/Project','main')"""
        )
        db.commit()
    rows = github_repository_sync._mapped_rows("owner/project", None)
    assert [row["id"] for row in rows] == [1]


def test_background_sync_contains_unexpected_failures(monkeypatch) -> None:
    def fail(*_args, **_kwargs):
        raise sqlite3.OperationalError("no such table: repositories")

    monkeypatch.setattr(github_repository_sync, "_synchronize_github_push", fail)

    result = github_repository_sync.synchronize_github_push(
        "example/project",
        "refs/heads/main",
        "abc123",
        123,
    )

    assert result == [
        {
            "repository_id": None,
            "state": "error",
            "detail": "Automatic GitHub pull failed: OperationalError",
        }
    ]

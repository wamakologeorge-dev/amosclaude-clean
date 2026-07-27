import sqlite3

import pytest

from amoscloud_ai import db_migrations


def test_migrations_are_idempotent(tmp_path):
    path = tmp_path / "auth.db"
    assert db_migrations.run_migrations(path) == [1, 2, 3, 4]
    assert db_migrations.run_migrations(path) == []
    with sqlite3.connect(path) as db:
        applied = db.execute(
            "SELECT version,name FROM schema_migrations ORDER BY version"
        ).fetchall()
        tables = {
            row[0]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        repository_columns = {
            row[1]
            for row in db.execute("PRAGMA table_info(repositories)").fetchall()
        }
        indexes = {
            row[1]
            for row in db.execute("PRAGMA index_list(repositories)").fetchall()
        }
        workspace_indexes = {
            row[1]
            for row in db.execute("PRAGMA index_list(cloud_workspaces)").fetchall()
        }

    assert applied == [
        (1, "developer_webhooks"),
        (2, "native_repository_base_schema"),
        (3, "github_repository_sync_schema"),
        (4, "cloud_workspaces"),
    ]
    assert {
        "developer_webhooks",
        "webhook_deliveries",
        "repositories",
        "repository_collaborators",
        "cloud_workspaces",
    } <= tables
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
    } <= repository_columns
    assert "idx_repositories_github_repository_id" in indexes
    assert "idx_repositories_github_full_name" in indexes
    assert "idx_cloud_workspaces_owner" in workspace_indexes


def test_github_schema_helper_is_idempotent(tmp_path):
    path = tmp_path / "isolated.db"
    with sqlite3.connect(path) as db:
        db.execute(
            """CREATE TABLE repositories (
                id INTEGER PRIMARY KEY,
                owner_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                visibility TEXT NOT NULL DEFAULT 'private',
                default_branch TEXT NOT NULL DEFAULT 'main',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )"""
        )
        db_migrations.ensure_github_repository_schema(db)
        db_migrations.ensure_github_repository_schema(db)
        db.commit()
        columns = {
            row[1]
            for row in db.execute("PRAGMA table_info(repositories)").fetchall()
        }
    assert "github_repository_id" in columns
    assert "github_last_sync_attempt_at" in columns


def test_migrations_reject_checksum_drift(tmp_path, monkeypatch):
    path = tmp_path / "auth.db"
    db_migrations.run_migrations(path)
    changed = db_migrations.Migration(1, "developer_webhooks", "SELECT 1;")
    monkeypatch.setattr(db_migrations, "MIGRATIONS", (changed,))
    with pytest.raises(RuntimeError, match="checksum"):
        db_migrations.run_migrations(path)

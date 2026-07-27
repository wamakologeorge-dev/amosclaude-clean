import sqlite3

import pytest

from amoscloud_ai import db_migrations


def test_migrations_are_idempotent(tmp_path):
    path = tmp_path / "auth.db"
    assert db_migrations.run_migrations(path) == [1, 2]
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

    assert applied == [
        (1, "developer_webhooks"),
        (2, "native_repository_base_schema"),
    ]
    assert {
        "developer_webhooks",
        "webhook_deliveries",
        "repositories",
        "repository_collaborators",
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
    } <= repository_columns


def test_migrations_reject_checksum_drift(tmp_path, monkeypatch):
    path = tmp_path / "auth.db"
    db_migrations.run_migrations(path)
    changed = db_migrations.Migration(1, "developer_webhooks", "SELECT 1;")
    monkeypatch.setattr(db_migrations, "MIGRATIONS", (changed,))
    with pytest.raises(RuntimeError, match="checksum"):
        db_migrations.run_migrations(path)

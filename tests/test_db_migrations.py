import sqlite3

import pytest

from amoscloud_ai import db_migrations


def test_migrations_are_idempotent(tmp_path):
    path = tmp_path / "auth.db"
    assert db_migrations.run_migrations(path) == [1]
    assert db_migrations.run_migrations(path) == []
    with sqlite3.connect(path) as db:
        assert (
            db.execute("SELECT name FROM schema_migrations").fetchone()[0] == "developer_webhooks"
        )
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"developer_webhooks", "webhook_deliveries"} <= tables


def test_migrations_reject_checksum_drift(tmp_path, monkeypatch):
    path = tmp_path / "auth.db"
    db_migrations.run_migrations(path)
    changed = db_migrations.Migration(1, "developer_webhooks", "SELECT 1;")
    monkeypatch.setattr(db_migrations, "MIGRATIONS", (changed,))
    with pytest.raises(RuntimeError, match="checksum"):
        db_migrations.run_migrations(path)

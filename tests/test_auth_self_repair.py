import sqlite3

from amoscloud_ai import auth_self_repair
from amoscloud_ai.api.routes import auth


def test_self_repair_preserves_users_and_creates_backup(monkeypatch, tmp_path):
    database = tmp_path / "auth.db"
    monkeypatch.setenv("AUTH_DB_PATH", str(database))
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "true")
    monkeypatch.setattr(auth_self_repair, "_database_path", lambda: database)
    monkeypatch.setattr(auth, "DB_PATH", database)

    with auth._connect() as db:
        db.execute(
            "INSERT INTO users(name,email,password_hash,provider,is_admin,created_at) VALUES (?,?,?,?,?,?)",
            ("Owner", "owner@amosclaud.com", "protected-hash", "password", 1, "2026-01-01T00:00:00+00:00"),
        )
        db.commit()

    result = auth_self_repair.diagnose_and_repair()

    assert result.status in {"healthy", "needs_configuration"}
    assert result.backup is not None
    with sqlite3.connect(database) as db:
        row = db.execute("SELECT email,password_hash FROM users").fetchone()
    assert row == ("owner@amosclaud.com", "protected-hash")


def test_self_repair_creates_missing_auth_directory(monkeypatch, tmp_path):
    database = tmp_path / "nested" / "auth.db"
    monkeypatch.setenv("AUTH_DB_PATH", str(database))
    monkeypatch.setattr(auth_self_repair, "_database_path", lambda: database)
    monkeypatch.setattr(auth, "DB_PATH", database)

    result = auth_self_repair.diagnose_and_repair()

    assert database.parent.is_dir()
    assert database.exists()
    assert any(check["name"] == "required-schema" and check["passed"] for check in result.checks)
    assert any("Never delete" in protection for protection in result.protections)

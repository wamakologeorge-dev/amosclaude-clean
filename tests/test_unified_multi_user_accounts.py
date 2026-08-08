import sqlite3
from pathlib import Path

from amoscloud_ai.api.routes.account import _account_usage, _positive_limit
from amoscloud_ai.api.routes.autonomous_keys import _active_key_count, _max_keys_per_user

ROOT = Path(__file__).resolve().parents[1]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_account_usage_counts_only_the_selected_user() -> None:
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript(
        """
        CREATE TABLE repositories (
            id INTEGER PRIMARY KEY,
            owner_id INTEGER NOT NULL
        );
        CREATE TABLE repository_collaborators (
            repository_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL
        );
        CREATE TABLE autonomous_api_keys (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            revoked_at TEXT
        );
        INSERT INTO repositories(id, owner_id) VALUES (1, 10), (2, 20), (3, 10);
        INSERT INTO repository_collaborators(repository_id, user_id)
        VALUES (2, 10), (1, 20);
        INSERT INTO autonomous_api_keys(id, user_id, revoked_at)
        VALUES (1, 10, NULL), (2, 10, 'revoked'), (3, 20, NULL);
        """
    )

    assert _account_usage(db, 10) == {
        "owned_repositories": 2,
        "shared_repositories": 1,
        "active_api_keys": 1,
    }
    assert _active_key_count(db, 10) == 1
    assert _active_key_count(db, 20) == 1


def test_per_user_limits_are_bounded_and_configurable(monkeypatch) -> None:
    monkeypatch.setenv("MAX_REPOSITORIES_PER_USER", "25")
    monkeypatch.setenv("MAX_AUTONOMOUS_KEYS_PER_USER", "7")

    assert _positive_limit("MAX_REPOSITORIES_PER_USER", 10) == 25
    assert _max_keys_per_user() == 7

    monkeypatch.setenv("MAX_AUTONOMOUS_KEYS_PER_USER", "0")
    assert _max_keys_per_user() == 1


def test_account_routes_describe_one_multi_user_platform() -> None:
    account = _source("amoscloud_ai/api/routes/account.py")
    keys = _source("amoscloud_ai/api/routes/autonomous_keys.py")

    assert '@router.get("/overview")' in account
    assert '"deployment_model": "single-service"' in account
    assert '"multi_user": True' in account
    assert '"account_isolation": "per-user"' in account
    assert '"admin_only": False' in account
    assert '"api_path": "/api/v1/agent/keys"' in account
    assert '"service_keys": {' in account
    assert '"autonomous_key_limit_reached"' in keys
    assert "WHERE user_id=? AND revoked_at IS NULL" in keys


def test_existing_signup_and_repository_storage_remain_per_user() -> None:
    auth = _source("amoscloud_ai/api/routes/auth.py")
    repositories = _source("amoscloud_ai/api/routes/repositories.py")

    assert "CREATE TABLE IF NOT EXISTS users" in auth
    assert "email TEXT NOT NULL UNIQUE COLLATE NOCASE" in auth
    assert "INSERT INTO users" in auth
    assert "UNIQUE(owner_id, name)" in repositories
    assert "FOREIGN KEY(owner_id) REFERENCES users(id)" in repositories
    assert "repository_collaborators" in repositories
    assert "WHERE r.owner_id=? OR c.user_id=? OR r.visibility='public'" in repositories

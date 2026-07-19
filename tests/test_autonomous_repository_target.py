import pytest
from fastapi import HTTPException

from amoscloud_ai.api.routes import auth, repositories


def _user(database: Path):
    auth.DB_PATH = database
    repositories.DB_PATH = database
    with auth._connect() as db:
        cursor = db.execute(
            "INSERT INTO users(name,email,password_hash,provider,is_admin,created_at) VALUES (?,?,?,'password',0,?)",
            ("Developer", "developer@example.com", "unused", "2026-07-19T00:00:00+00:00"),
        )
        db.commit()
        return db.execute("SELECT * FROM users WHERE id=?", (cursor.lastrowid,)).fetchone()


def test_repository_context_targets_owned_managed_git_workspace(tmp_path, monkeypatch):
    database = tmp_path / "auth.db"
    repository_root = tmp_path / "repositories"
    monkeypatch.setattr(auth, "DB_PATH", database)
    monkeypatch.setattr(repositories, "DB_PATH", database)
    monkeypatch.setattr(repositories, "REPOSITORY_ROOT", repository_root)
    user = _user(database)

    repository = repositories.create_repository(
        repositories.RepositoryCreate(name="customer-project"),
        user,
    )
    context = repositories.agent_repository_context(repository.id, user["id"], require_write=True)

    assert context["repository_id"] == repository.id
    assert context["repository_role"] == "owner"
    assert context["trusted_repository_workspace"] == str((repository_root / str(repository.id)).resolve())


def test_repository_context_rejects_another_users_private_repository(tmp_path, monkeypatch):
    database = tmp_path / "auth.db"
    repository_root = tmp_path / "repositories"
    monkeypatch.setattr(auth, "DB_PATH", database)
    monkeypatch.setattr(repositories, "DB_PATH", database)
    monkeypatch.setattr(repositories, "REPOSITORY_ROOT", repository_root)
    owner = _user(database)
    with auth._connect() as db:
        cursor = db.execute(
            "INSERT INTO users(name,email,password_hash,provider,is_admin,created_at) VALUES (?,?,?,'password',0,?)",
            ("Other", "other@example.com", "unused", "2026-07-19T00:00:00+00:00"),
        )
        db.commit()
        other_id = cursor.lastrowid
    repository = repositories.create_repository(
        repositories.RepositoryCreate(name="private-project"),
        owner,
    )

    with pytest.raises(HTTPException) as error:
        repositories.agent_repository_context(repository.id, other_id)

    assert error.value.status_code == 404

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from amoscloud_ai import agent_actions
from amoscloud_ai.api.routes import auth, repositories


def configure_storage(tmp_path, monkeypatch):
    database = tmp_path / "auth.db"
    repository_root = tmp_path / "repositories"
    monkeypatch.setattr(auth, "DB_PATH", database)
    monkeypatch.setattr(repositories, "DB_PATH", database)
    monkeypatch.setattr(repositories, "REPOSITORY_ROOT", repository_root)
    return database, repository_root


def create_session(email: str = "developer@example.com") -> str:
    token = "test-session-token"
    now = datetime.now(timezone.utc)
    with auth._connect() as db:
        cursor = db.execute(
            "INSERT INTO users(name,email,password_hash,provider,is_admin,created_at) VALUES (?,?,?,'password',0,?)",
            ("Developer", email, auth._hash_password("strong-password"), now.isoformat()),
        )
        db.execute(
            "INSERT INTO sessions(token_hash,user_id,expires_at,created_at) VALUES (?,?,?,?)",
            (
                auth._token_hash(token),
                cursor.lastrowid,
                (now + timedelta(hours=1)).isoformat(),
                now.isoformat(),
            ),
        )
        db.commit()
    return token


def test_parse_explicit_public_repository_command():
    command = agent_actions.parse_repository_create_command(
        'Create a public repository for Amosclaud description "Real platform repository"'
    )
    assert command is not None
    assert command["name"] == "Amosclaud"
    assert command["visibility"] == "public"
    assert command["description"] == "Real platform repository"
    assert command["initialize_readme"] is True


def test_parse_default_private_repository_command():
    command = agent_actions.parse_repository_create_command("Create repository for Amosclaud")
    assert command is not None
    assert command["name"] == "Amosclaud"
    assert command["visibility"] == "private"


def test_parse_explicit_private_repo_command():
    command = agent_actions.parse_repository_create_command("Please make a private repo named backend-api")
    assert command is not None
    assert command["name"] == "backend-api"
    assert command["visibility"] == "private"


def test_agent_creates_real_native_repository(tmp_path, monkeypatch):
    _, repository_root = configure_storage(tmp_path, monkeypatch)
    token = create_session()

    repository = agent_actions.execute_repository_create(
        "Create repository for Amosclaud",
        token,
    )

    assert repository is not None
    assert repository.name == "Amosclaud"
    assert repository.role == "owner"
    repository_path = repository_root / str(repository.id)
    assert (repository_path / ".git").is_dir()
    assert (repository_path / "README.md").read_text(encoding="utf-8").startswith("# Amosclaud")
    assert (repository_path / ".Amosclaud-workflow" / "workflow.yml").is_file()


def test_agent_repository_action_requires_login(tmp_path, monkeypatch):
    configure_storage(tmp_path, monkeypatch)
    with pytest.raises(HTTPException) as error:
        agent_actions.execute_repository_create("Create repository for Amosclaud", None)
    assert error.value.status_code == 401


def test_non_action_message_is_not_executed(tmp_path, monkeypatch):
    configure_storage(tmp_path, monkeypatch)
    assert agent_actions.execute_repository_create("How do repositories work?", None) is None

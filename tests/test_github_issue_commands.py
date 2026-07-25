"""Tests for issue-driven Amosclaud commands on the GitHub App webhook.

Every GitHub HTTP call, model call, and task execution is stubbed: the suite
never touches the network.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from datetime import datetime, timezone

import httpx
import pytest

from amoscloud_ai import agent_tokens, codex_memory, github_issue_commands
from amoscloud_ai.api.routes import (
    auth,
    github_app,
    github_repositories,
    repositories,
    task_router,
)
from amoscloud_ai.main import create_app

app = create_app()

SECRET = "test-webhook-secret"
REPOSITORY = "wamakologeorge-dev/amosclaude-clean"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AMOSCLAUD_CODEX_MEMORY_DIR", str(tmp_path / "codex"))
    monkeypatch.setenv("AMOSCLAUD_GITHUB_EVENTS_DB", str(tmp_path / "events.db"))
    monkeypatch.setenv("GITHUB_APP_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("AMOSCLAUD_GITHUB_COMMANDS_INLINE", "1")
    monkeypatch.delenv("AMOSCLAUD_GITHUB_COMMENT_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("AMOSCLAUD_GITHUB_COMMAND_ALLOWLIST", raising=False)
    database = tmp_path / "platform.db"
    monkeypatch.setattr(auth, "DB_PATH", database)
    monkeypatch.setattr(repositories, "DB_PATH", database)
    monkeypatch.setattr(github_repositories, "DB_PATH", database)
    codex_memory.reset_cache_for_tests()
    yield
    codex_memory.reset_cache_for_tests()


def request(method: str, path: str, **kwargs):
    async def _go():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(_go())


def deliver(event: str, payload: dict, *, delivery: str = "delivery-1"):
    body = json.dumps(payload).encode()
    digest = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    return request(
        "POST",
        "/api/v1/agent/github/webhook",
        content=body,
        headers={
            "X-GitHub-Event": event,
            "X-GitHub-Delivery": delivery,
            "X-Hub-Signature-256": f"sha256={digest}",
            "Content-Type": "application/json",
        },
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _account(
    *,
    login: str = "wamakologeorge-dev",
    linked: bool = True,
    role: str | None = None,
    credits: int = 100,
) -> int:
    """Create a platform account, its GitHub link, and the imported repository."""
    with auth._connect() as db:
        db.commit()
    with repositories._db() as db:
        cursor = db.execute(
            "INSERT INTO users(name,email,provider,is_admin,created_at)"
            " VALUES (?,?,?,0,?)",
            ("Issue Commander", f"{login}@example.com", "password", _now()),
        )
        account_id = int(cursor.lastrowid)
        owner_id = account_id
        if role:
            other = db.execute(
                "INSERT INTO users(name,email,provider,is_admin,created_at)"
                " VALUES (?,?,?,0,?)",
                ("Repository Owner", "owner@example.com", "password", _now()),
            )
            owner_id = int(other.lastrowid)
        repository_row = db.execute(
            "INSERT INTO repositories(owner_id,name,description,visibility,"
            "default_branch,created_at,updated_at) VALUES (?,?,'','private',"
            "'main',?,?)",
            (owner_id, "amosclaude-clean", _now(), _now()),
        )
        repository_id = int(repository_row.lastrowid)
        if role:
            db.execute(
                "INSERT INTO repository_collaborators(repository_id,user_id,role,"
                "created_at) VALUES (?,?,?,?)",
                (repository_id, account_id, role, _now()),
            )
        db.commit()
    with github_repositories._db() as db:
        db.execute(
            "UPDATE repositories SET github_full_name=?,github_default_branch='main'"
            " WHERE id=?",
            (REPOSITORY, repository_id),
        )
        if linked:
            db.execute(
                "INSERT INTO github_connections(user_id,github_id,github_login,"
                "access_token_ciphertext,scopes,connected_at,updated_at)"
                " VALUES (?,?,?,?,'repo',?,?)",
                (account_id, str(account_id), login, "cipher", _now(), _now()),
            )
        db.commit()
    with auth._connect() as db:
        agent_tokens.credit_tokens(
            db, account_id, credits, reason="test_credit", reference="test-1"
        )
    return account_id


def _comment_payload(
    body: str,
    *,
    login: str = "wamakologeorge-dev",
    association: str = "OWNER",
    action: str = "created",
    comment_id: int = 555,
    sender_type: str = "User",
) -> dict:
    return {
        "action": action,
        "repository": {"full_name": REPOSITORY},
        "sender": {"login": login, "type": sender_type},
        "issue": {
            "number": 42,
            "title": "Tests fail after the last merge",
            "html_url": f"https://github.com/{REPOSITORY}/issues/42",
        },
        "comment": {
            "id": comment_id,
            "body": body,
            "author_association": association,
            "user": {"login": login},
        },
    }


def _issue_payload(
    *,
    action: str = "opened",
    body: str = "",
    labels: list[str] | None = None,
    label: str | None = None,
    login: str = "wamakologeorge-dev",
    association: str = "OWNER",
) -> dict:
    payload = {
        "action": action,
        "repository": {"full_name": REPOSITORY},
        "sender": {"login": login, "type": "User"},
        "issue": {
            "number": 43,
            "title": "Repair the failing authentication test",
            "body": body,
            "author_association": association,
            "html_url": f"https://github.com/{REPOSITORY}/issues/43",
            "labels": [{"name": name} for name in labels or []],
        },
    }
    if label:
        payload["label"] = {"name": label}
    return payload


@pytest.fixture
def _no_runtime(monkeypatch):
    monkeypatch.setattr(github_issue_commands, "_runtime_ready", lambda: False)


@pytest.fixture
def _relayed(monkeypatch):
    """Capture outbound issue comments instead of calling GitHub."""
    monkeypatch.setenv("AMOSCLAUD_GITHUB_COMMENT_TOKEN", "test-comment-token")
    posted: list[dict] = []

    def _fake_post(repository, issue_number, body, token):
        assert token == "test-comment-token"
        posted.append(
            {"repository": repository, "issue": issue_number, "body": body}
        )
        return True, f"https://github.com/{repository}/issues/{issue_number}#c1"

    monkeypatch.setattr(github_issue_commands, "_post_comment", _fake_post)
    return posted


# ---------------------------------------------------------------- parsing


def test_parses_slash_mention_and_label_commands():
    parsed = github_issue_commands.parse_issue_command(
        "issue_comment", _comment_payload("/amosclaud fix the failing auth test")
    )
    assert parsed and parsed.command == "fix"
    assert parsed.instruction == "the failing auth test"
    assert parsed.source == "comment"

    mention = github_issue_commands.parse_issue_command(
        "issue_comment", _comment_payload("Hey @amosclaud plan a safe repair")
    )
    assert mention and mention.command == "plan"
    assert mention.instruction == "a safe repair"

    for command in ("review", "explain"):
        variant = github_issue_commands.parse_issue_command(
            "issue_comment", _comment_payload(f"@amosclaud {command} this change")
        )
        assert variant and variant.command == command

    labelled = github_issue_commands.parse_issue_command(
        "issues", _issue_payload(action="labeled", label="amosclaud:fix")
    )
    assert labelled and labelled.command == "fix" and labelled.source == "label"

    from_body = github_issue_commands.parse_issue_command(
        "issues", _issue_payload(body="/amosclaud review the regression")
    )
    assert from_body and from_body.command == "review"


def test_non_command_activity_is_ignored_and_only_recorded(monkeypatch):
    called: list[str] = []
    monkeypatch.setattr(
        github_issue_commands, "_claim", lambda *a, **k: called.append("claim")
    )
    assert (
        github_issue_commands.parse_issue_command(
            "issue_comment", _comment_payload("Thanks, this looks unrelated")
        )
        is None
    )
    assert (
        github_issue_commands.parse_issue_command(
            "issues", _issue_payload(body="Plain bug report with no command")
        )
        is None
    )
    response = deliver("issue_comment", _comment_payload("just a normal comment"))
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True and body["handled"] is True
    assert "issue_command" not in body
    assert called == []


def test_closed_issue_action_is_not_parsed():
    assert (
        github_issue_commands.parse_issue_command(
            "issues", _issue_payload(action="closed", body="/amosclaud fix it")
        )
        is None
    )


# ------------------------------------------------------- authorization


def test_bot_and_self_comments_are_ignored():
    bot = deliver(
        "issue_comment",
        _comment_payload("/amosclaud fix it", login="dependabot[bot]"),
    )
    assert bot.json()["issue_command"] == {
        "status": "ignored",
        "reason": "bot_sender",
        "command": "fix",
    }
    typed = deliver(
        "issue_comment",
        _comment_payload("/amosclaud fix it", login="someone", sender_type="Bot"),
        delivery="delivery-bot-2",
    )
    assert typed.json()["issue_command"]["reason"] == "bot_sender"
    assert (
        github_issue_commands.parse_issue_command(
            "issue_comment",
            _comment_payload(
                f"{github_issue_commands.MARKER}\n### Amosclaud accepted this request"
            ),
        )
        is None
    )


def test_refusal_when_sender_has_no_linked_account(_relayed):
    _account(login="wamakologeorge-dev", linked=False)
    response = deliver("issue_comment", _comment_payload("/amosclaud fix the tests"))
    outcome = response.json()["issue_command"]
    assert outcome["status"] == "refused"
    assert outcome["reason"] == "no_linked_account"
    assert outcome["relay_state"] == "delivered"
    assert "did not run this command" in _relayed[0]["body"]
    with auth._connect() as db:
        task_router._ensure_schema(db)
        assert db.execute("SELECT COUNT(*) FROM global_tasks").fetchone()[0] == 0


def test_refusal_when_linked_account_lacks_repository_write_access(_relayed):
    _account(role="viewer")
    response = deliver("issue_comment", _comment_payload("/amosclaud fix the tests"))
    outcome = response.json()["issue_command"]
    assert outcome["status"] == "refused"
    assert outcome["reason"] == "no_repository_write_access"
    with auth._connect() as db:
        task_router._ensure_schema(db)
        assert db.execute("SELECT COUNT(*) FROM global_tasks").fetchone()[0] == 0


def test_refusal_when_association_is_untrusted(_relayed):
    _account()
    response = deliver(
        "issue_comment",
        _comment_payload("/amosclaud fix the tests", association="NONE"),
    )
    outcome = response.json()["issue_command"]
    assert outcome["status"] == "refused"
    assert outcome["reason"] == "untrusted_association"


def test_allowlisted_sender_without_association_is_authorized(
    monkeypatch, _relayed, _no_runtime
):
    _account(login="outside-helper")
    monkeypatch.setenv("AMOSCLAUD_GITHUB_COMMAND_ALLOWLIST", "outside-helper, other")
    response = deliver(
        "issue_comment",
        _comment_payload(
            "/amosclaud fix the tests", login="outside-helper", association="NONE"
        ),
    )
    assert response.json()["issue_command"]["status"] == "blocked"


# ------------------------------------------------- task creation + replay


def test_authorized_command_creates_exactly_one_task(monkeypatch, _relayed):
    account_id = _account()
    monkeypatch.setattr(github_issue_commands, "_runtime_ready", lambda: True)
    executed: list[str] = []

    def _fake_execute(task_id: str) -> None:
        executed.append(task_id)
        with auth._connect() as db:
            db.execute(
                "UPDATE global_tasks SET status='completed',summary=?,"
                "pull_request_url=?,verification_id=?,artifacts_json=? WHERE id=?",
                (
                    "Applied the smallest safe repair.",
                    f"https://github.com/{REPOSITORY}/pull/601",
                    "verify_abc123",
                    json.dumps([{"type": "verification", "commit_sha": "cafe1234"}]),
                    task_id,
                ),
            )
            task_router._event(
                db,
                task_id,
                "task.completed",
                "done",
                {"evidence": ["pytest: 771 passed"]},
            )
            db.commit()

    monkeypatch.setattr(github_issue_commands, "_execute_task", _fake_execute)
    response = deliver(
        "issue_comment", _comment_payload("/amosclaud fix the failing auth test")
    )
    outcome = response.json()["issue_command"]
    assert outcome["status"] == "accepted"
    assert outcome["mode"] == "fix"
    assert outcome["repository"] == REPOSITORY
    task_id = outcome["task_id"]
    assert executed == [task_id]

    with auth._connect() as db:
        rows = db.execute("SELECT * FROM global_tasks").fetchall()
    assert len(rows) == 1
    assert rows[0]["id"] == task_id
    assert rows[0]["repository"] == REPOSITORY
    assert rows[0]["user_id"] == account_id
    assert rows[0]["execution_target"] == "github"
    assert rows[0]["mode"] == "fix"
    assert json.loads(rows[0]["metadata_json"])["github"]["issue_number"] == 42

    bodies = [item["body"] for item in _relayed]
    assert len(bodies) == 2
    assert task_id in bodies[0] and "accepted this request" in bodies[0]
    assert f"https://github.com/{REPOSITORY}/pull/601" in bodies[1]
    assert "`cafe1234`" in bodies[1]
    assert "pytest: 771 passed" in bodies[1]
    assert "verify_abc123" in bodies[1]


def test_replayed_delivery_never_runs_twice(monkeypatch, _relayed, _no_runtime):
    _account()
    payload = _comment_payload("/amosclaud fix the failing auth test")
    first = deliver("issue_comment", payload).json()["issue_command"]
    assert first["status"] == "blocked"
    replay = deliver("issue_comment", payload).json()["issue_command"]
    assert replay["status"] == "already_handled"
    assert replay["task_id"] == first["task_id"]

    edited = dict(payload, action="edited")
    same_comment = deliver(
        "issue_comment", edited, delivery="delivery-2"
    ).json()["issue_command"]
    assert same_comment["status"] == "already_handled"

    with auth._connect() as db:
        assert db.execute("SELECT COUNT(*) FROM global_tasks").fetchone()[0] == 1
    assert len(_relayed) == 2


def test_blocker_is_truthful_when_no_model_runtime(_relayed, _no_runtime):
    _account()
    response = deliver("issue_comment", _comment_payload("/amosclaud fix the tests"))
    outcome = response.json()["issue_command"]
    assert outcome["status"] == "blocked"
    assert outcome["reason"] == "no_model_runtime"
    with auth._connect() as db:
        row = db.execute(
            "SELECT * FROM global_tasks WHERE id=?", (outcome["task_id"],)
        ).fetchone()
    assert row["status"] == "completed"
    assert "no code changes" in row["summary"]
    assert "Native repository actions" in row["summary"]
    assert row["verification_id"]
    assert row["pull_request_url"] is None
    completion = _relayed[-1]["body"]
    assert "no Amosclaud model runtime is connected" in completion
    assert "`none`" in completion


def test_pending_relay_when_no_github_credential(_no_runtime):
    _account()
    response = deliver("issue_comment", _comment_payload("/amosclaud fix the tests"))
    outcome = response.json()["issue_command"]
    assert outcome["relay_state"] == "pending"
    pending = github_issue_commands.pending_relays()
    kinds = {item["kind"] for item in pending}
    assert kinds == {"acknowledgement", "completion"}
    assert all(item["repository"] == REPOSITORY for item in pending)
    assert "No GitHub write credential" in pending[0]["detail"]


# ---------------------------------------------------------- visibility


def test_issue_command_feed_requires_authentication_and_lists_bindings(
    monkeypatch, _relayed, _no_runtime
):
    _account()
    assert request("GET", "/api/v1/agent/github/issue-commands").status_code == 401
    deliver("issue_comment", _comment_payload("/amosclaud fix the tests"))
    monkeypatch.setattr(
        github_app, "_authenticated_user", lambda _request: {"id": 1, "name": "Owner"}
    )
    response = request("GET", "/api/v1/agent/github/issue-commands")
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    item = body["issue_commands"][0]
    assert item["issue"] == f"{REPOSITORY}#42"
    assert item["command"] == "fix"
    assert item["authorized"] is True
    assert item["authorization_outcome"] == "authorized"
    assert item["task_status"] == "completed"
    assert item["relay_state"] == "delivered"
    assert "amosclaud:fix" in body["labels"]

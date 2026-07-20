from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import httpx

from amoscloud_ai import agent_tokens
from amoscloud_ai.api.routes import auth, task_router
from amoscloud_ai.main import create_app

app = create_app()


async def _request(method: str, path: str, **kwargs):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        return await client.request(method, path, **kwargs)


def request(method: str, path: str, **kwargs):
    return asyncio.run(_request(method, path, **kwargs))


def _account(monkeypatch, tmp_path):
    auth.DB_PATH = tmp_path / "task-router.db"
    with auth._connect() as db:
        cursor = db.execute(
            "INSERT INTO users(name,email,provider,is_admin,created_at) VALUES (?,?,?,0,?)",
            (
                "Router User",
                "router@example.com",
                "password",
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        user_id = int(cursor.lastrowid)
        db.commit()
        agent_tokens.credit_tokens(
            db, user_id, 100, reason="test_credit", reference="test-credit-1"
        )
    monkeypatch.setattr(
        task_router,
        "get_user_from_session",
        lambda _token: {"id": user_id, "name": "Router User"},
    )
    return user_id


def test_task_approval_runner_claim_and_completion(monkeypatch, tmp_path):
    _account(monkeypatch, tmp_path)
    runner = request(
        "POST",
        "/api/v1/runners",
        json={"name": "Test runner"},
        cookies={"amos_session": "test"},
    )
    assert runner.status_code == 201
    runner_id = runner.json()["id"]
    token = runner.json()["runner_token"]

    created = request(
        "POST",
        "/api/v1/tasks",
        json={
            "objective": "Fix the failing tests",
            "repository": "owner/project",
            "mode": "build",
            "delivery": "pull_request",
            "execution_target": "self_hosted",
            "runner_id": runner_id,
            "require_approval": True,
        },
        cookies={"amos_session": "test"},
    )
    assert created.status_code == 202
    task_id = created.json()["id"]
    assert created.json()["status"] == "awaiting_approval"

    approved = request(
        "POST", f"/api/v1/tasks/{task_id}/approve", cookies={"amos_session": "test"}
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "queued"

    claimed = request(
        "POST",
        f"/api/v1/runners/{runner_id}/claim",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert claimed.status_code == 200
    assert claimed.json()["id"] == task_id
    assert claimed.json()["status"] == "running"

    completed = request(
        "POST",
        f"/api/v1/runners/{runner_id}/tasks/{task_id}/complete",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "status": "completed",
            "summary": "Tests fixed and verified.",
            "evidence": ["pytest: passed"],
            "pull_request_url": "https://github.com/owner/project/pull/1",
        },
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"


def test_cancel_refunds_reserved_credits(monkeypatch, tmp_path):
    user_id = _account(monkeypatch, tmp_path)
    created = request(
        "POST",
        "/api/v1/tasks",
        json={
            "objective": "Review this project",
            "mode": "review",
            "require_approval": True,
        },
        cookies={"amos_session": "test"},
    )
    task_id = created.json()["id"]
    cancelled = request(
        "POST", f"/api/v1/tasks/{task_id}/cancel", cookies={"amos_session": "test"}
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    with auth._connect() as db:
        balance = db.execute(
            "SELECT balance FROM agent_token_wallets WHERE user_id=?", (user_id,)
        ).fetchone()[0]
    assert balance == 100


def test_runner_cannot_claim_another_accounts_task(monkeypatch, tmp_path):
    first_user = _account(monkeypatch, tmp_path)
    first_runner = request(
        "POST",
        "/api/v1/runners",
        json={"name": "First runner"},
        cookies={"amos_session": "first"},
    ).json()
    created = request(
        "POST",
        "/api/v1/tasks",
        json={
            "objective": "Private owner task",
            "mode": "build",
            "execution_target": "self_hosted",
            "runner_id": first_runner["id"],
            "require_approval": False,
        },
        cookies={"amos_session": "first"},
    )
    assert created.status_code == 202

    with auth._connect() as db:
        cursor = db.execute(
            "INSERT INTO users(name,email,provider,is_admin,created_at) VALUES (?,?,?,0,?)",
            (
                "Second User",
                "second@example.com",
                "password",
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        second_user = int(cursor.lastrowid)
        db.commit()
    assert second_user != first_user
    monkeypatch.setattr(
        task_router,
        "get_user_from_session",
        lambda _token: {"id": second_user, "name": "Second User"},
    )
    runner = request(
        "POST",
        "/api/v1/runners",
        json={"name": "Second runner"},
        cookies={"amos_session": "second"},
    ).json()
    response = request(
        "POST",
        f"/api/v1/runners/{runner['id']}/claim",
        headers={"Authorization": f"Bearer {runner['runner_token']}"},
    )
    assert response.status_code == 200
    assert response.json() is None


def test_auto_routing_contract(monkeypatch, tmp_path):
    _account(monkeypatch, tmp_path)

    cloud = request(
        "POST",
        "/api/v1/tasks",
        json={
            "objective": "Explain the failing build",
            "mode": "ask",
            "require_approval": True,
        },
        cookies={"amos_session": "test"},
    )
    assert cloud.status_code == 202
    assert cloud.json()["execution_target"] == "cloud"

    github = request(
        "POST",
        "/api/v1/tasks",
        json={
            "objective": "Fix the failing build",
            "repository": "owner/project",
            "require_approval": True,
        },
        cookies={"amos_session": "test"},
    )
    assert github.status_code == 202
    assert github.json()["execution_target"] == "github"

    invalid = request(
        "POST",
        "/api/v1/tasks",
        json={"objective": "Run locally", "execution_target": "self_hosted"},
        cookies={"amos_session": "test"},
    )
    assert invalid.status_code == 422

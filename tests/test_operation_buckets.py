from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import httpx

from amoscloud_ai import agent_tokens
from amoscloud_ai.api.routes import auth, operation_buckets, task_router
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


def _account(monkeypatch, tmp_path) -> int:
    auth.DB_PATH = tmp_path / "operation-buckets.db"
    with auth._connect() as db:
        cursor = db.execute(
            """
            INSERT INTO users(name,email,provider,is_admin,created_at)
            VALUES (?,?,?,0,?)
            """,
            (
                "Bucket User",
                "bucket@example.com",
                "password",
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        user_id = int(cursor.lastrowid)
        db.commit()
        agent_tokens.credit_tokens(
            db,
            user_id,
            100,
            reason="test_credit",
            reference="bucket-credit",
        )
    identity = lambda _token: {"id": user_id, "name": "Bucket User"}
    monkeypatch.setattr(task_router, "get_user_from_session", identity)
    monkeypatch.setattr(operation_buckets, "get_user_from_session", identity)
    return user_id


def test_bucket_groups_owned_tasks_and_verified_results(monkeypatch, tmp_path):
    _account(monkeypatch, tmp_path)
    runner = request(
        "POST",
        "/api/v1/runners",
        json={"name": "Bucket runner"},
        cookies={"amos_session": "test"},
    ).json()
    created = request(
        "POST",
        "/api/v1/tasks",
        json={
            "objective": "Fix the repository and return evidence",
            "repository": "owner/project",
            "mode": "fix",
            "execution_target": "self_hosted",
            "runner_id": runner["id"],
            "require_approval": False,
        },
        cookies={"amos_session": "test"},
    )
    assert created.status_code == 202
    task = created.json()
    assert task["bucket_id"].startswith("bucket_")

    claimed = request(
        "POST",
        f"/api/v1/runners/{runner['id']}/claim",
        headers={"Authorization": f"Bearer {runner['runner_token']}"},
    )
    assert claimed.status_code == 200
    completed = request(
        "POST",
        f"/api/v1/runners/{runner['id']}/tasks/{task['id']}/complete",
        headers={"Authorization": f"Bearer {runner['runner_token']}"},
        json={
            "status": "completed",
            "summary": "Repository fixed and verified.",
            "evidence": ["pytest: passed", "Doctor: passed"],
            "verification_id": "verify_bucket_12345678",
            "artifacts": [
                {
                    "type": "pull_request",
                    "url": "https://github.com/owner/project/pull/7",
                }
            ],
            "pull_request_url": "https://github.com/owner/project/pull/7",
        },
    )
    assert completed.status_code == 200

    bucket = request(
        "GET",
        "/api/v1/operations/bucket",
        cookies={"amos_session": "test"},
    )
    assert bucket.status_code == 200
    result = bucket.json()
    assert result["id"] == task["bucket_id"]
    assert result["counts"]["operations"] == 1
    assert result["counts"]["verified_results"] == 1
    assert result["operations"][0]["verification_id"] == "verify_bucket_12345678"
    assert result["operations"][0]["artifacts"][0]["type"] == "pull_request"

    events = request(
        "GET",
        "/api/v1/operations/bucket/events",
        cookies={"amos_session": "test"},
    )
    assert events.status_code == 200
    assert any(
        event["event_type"] == "task.completed"
        and event["details"]["verification_id"] == "verify_bucket_12345678"
        for event in events.json()
    )


def test_each_user_receives_a_different_bucket(monkeypatch, tmp_path):
    first_user = _account(monkeypatch, tmp_path)
    with auth._connect() as db:
        first = operation_buckets.ensure_user_bucket(db, first_user)
        cursor = db.execute(
            """
            INSERT INTO users(name,email,provider,is_admin,created_at)
            VALUES (?,?,?,0,?)
            """,
            (
                "Second Bucket User",
                "bucket2@example.com",
                "password",
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        second_user = int(cursor.lastrowid)
        db.commit()
        second = operation_buckets.ensure_user_bucket(db, second_user)
    assert first["id"] != second["id"]
    assert first["user_id"] == first_user
    assert second["user_id"] == second_user

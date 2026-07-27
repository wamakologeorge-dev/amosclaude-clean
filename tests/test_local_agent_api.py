from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from amoscloud_ai.local_cloud.app import create_app
from amoscloud_ai.local_cloud.authority import LocalAuthority
from amoscloud_ai.local_cloud.executor import LocalJobManager


def test_internal_heal_and_build_queues_fixed_guarded_action(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / "state"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("AMOSCLAUD_LOCAL_STATE_DIR", str(state_dir))
    monkeypatch.setenv("AMOSCLAUD_LOCAL_ALLOWED_ROOTS", str(tmp_path))

    authority = LocalAuthority(state_dir)
    _, token = authority.initialize()
    assert token is not None

    # Keep this API contract test deterministic. AgentBuildGuard behavior has its
    # own tests; here we verify authentication, confirmation, and action mapping.
    monkeypatch.setattr(LocalJobManager, "_execute", lambda *args, **kwargs: None)
    client = TestClient(create_app())
    headers = {"Authorization": f"Bearer {token}"}

    registered = client.post(
        "/v1/workspaces",
        headers=headers,
        json={"name": "Workspace", "path": str(workspace)},
    )
    assert registered.status_code == 201
    workspace_id = registered.json()["id"]

    rejected = client.post(
        "/api/agent/heal-and-build",
        headers=headers,
        json={
            "workspace_id": workspace_id,
            "target": "verify_python",
            "confirmation": "yes",
        },
    )
    assert rejected.status_code == 422

    accepted = client.post(
        "/api/agent/heal-and-build",
        headers=headers,
        json={
            "workspace_id": workspace_id,
            "target": "verify_python",
            "confirmation": f"HEAL {workspace_id} verify_python",
        },
    )
    assert accepted.status_code == 202
    payload = accepted.json()
    assert payload["action"] == "guarded_verify_python"
    assert payload["target"] == "verify_python"
    assert payload["maximum_attempts"] == 3
    assert payload["status_url"] == f"/v1/jobs/{payload['id']}"


def test_internal_heal_and_build_requires_local_authority_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / "state"
    monkeypatch.setenv("AMOSCLAUD_LOCAL_STATE_DIR", str(state_dir))
    LocalAuthority(state_dir).initialize()
    client = TestClient(create_app())

    response = client.post(
        "/api/agent/heal-and-build",
        json={
            "workspace_id": "ws_00000000000000000000000000000000",
            "target": "verify_python",
            "confirmation": "HEAL ws_00000000000000000000000000000000 verify_python",
        },
    )
    assert response.status_code == 401

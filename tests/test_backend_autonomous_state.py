from pathlib import Path

from amoscloud_ai.api.routes import autonomous_state
from amoscloud_ai.main import create_app


def _owner():
    return {"id": 42, "name": "George", "email": "george@example.com", "is_admin": 1}


def test_backend_autonomous_routes_are_registered():
    paths = {route.path for route in create_app().routes}

    assert "/api/v1/agent/autonomous/messages" in paths
    assert "/api/v1/agent/autonomous/sessions/current" in paths
    assert "/api/v1/agent/autonomous/results" in paths
    assert "/api/v1/agent/autonomous/results/{result_id}" in paths
    assert "/api/v1/agent/autonomous/dashboard" in paths


def test_conversation_objective_and_real_result_survive_backend_reload(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTONOMOUS_STATE_DB", str(tmp_path / "autonomous.db"))
    owner = _owner()

    message = autonomous_state.save_message(
        autonomous_state.MessageWrite(content="Create a source bundle", repository_id="repo-7"),
        owner=owner,
    )
    autonomous_state.update_session(
        message["session_id"],
        autonomous_state.SessionPatch(
            active_objective="Create the confirmed source bundle",
            status="ready",
        ),
        owner=owner,
    )
    saved = autonomous_state.save_result(
        autonomous_state.ResultWrite(
            session_id=message["session_id"],
            result_type="bundle",
            title="Source bundle",
            status="verified",
            summary="The real archive was created and verified.",
            payload={"bundle_id": "bundle-123", "archive_sha256": "abc123"},
        ),
        owner=owner,
    )

    current = autonomous_state.current_session(owner=owner)
    result = autonomous_state.get_result(saved["result_id"], owner=owner)
    dashboard = autonomous_state.dashboard(owner=owner)

    assert current["session"]["active_objective"] == "Create the confirmed source bundle"
    assert current["session"]["repository_id"] == "repo-7"
    assert current["messages"][0]["content"] == "Create a source bundle"
    assert result["payload"]["bundle_id"] == "bundle-123"
    assert result["payload"]["archive_sha256"] == "abc123"
    assert dashboard["total_results"] == 1
    assert dashboard["successful_results"] == 1
    assert dashboard["recent_results"][0]["id"] == saved["result_id"]


def test_state_module_contains_no_frontend_generated_placeholder_records():
    source = Path(autonomous_state.__file__).read_text(encoding="utf-8").lower()

    for forbidden in ("sample result", "demo result", "fake result", "placeholder result"):
        assert forbidden not in source

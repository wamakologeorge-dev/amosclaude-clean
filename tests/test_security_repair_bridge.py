from __future__ import annotations

from typing import Any

from amoscloud_ai.github_app_connection import InstallationConnection
from amoscloud_ai.security_repair_bridge import bridge_security_failure


def connection() -> InstallationConnection:
    return InstallationConnection(
        token="installation-token",
        app_slug="amosclaud-bot",
        bot_login="amosclaud-bot[bot]",
        bot_user_id="24680",
        repository="owner/repo",
    )


def event(
    *,
    workflow: str = "CodeQL",
    conclusion: str = "failure",
    head_sha: str = "abc123",
    pull_number: int | None = 7,
) -> dict[str, Any]:
    pulls = [] if pull_number is None else [{"number": pull_number}]
    return {
        "repository": {"default_branch": "main"},
        "workflow_run": {
            "id": 99,
            "name": workflow,
            "conclusion": conclusion,
            "head_sha": head_sha,
            "html_url": "https://github.com/owner/repo/actions/runs/99",
            "pull_requests": pulls,
        },
    }


def dispatching_request(calls: list[tuple[str, str, dict[str, Any] | None]]):
    def request(method, url, headers, payload):
        calls.append((method, url, payload))
        assert headers["Authorization"] == "Bearer installation-token"
        if url.endswith("/pulls/7"):
            return 200, {"state": "open", "head": {"sha": "abc123"}}
        if url.endswith("/amosclaud-repair-control-plane.yml/dispatches"):
            return 204, {}
        raise AssertionError((method, url, payload))

    return request


def test_failed_security_workflow_dispatches_existing_repair_control_plane() -> None:
    calls: list[tuple[str, str, dict[str, Any] | None]] = []

    result = bridge_security_failure(
        repository="owner/repo",
        event=event(),
        connection=connection(),
        request=dispatching_request(calls),
    )

    assert result.status == "REPAIR_DISPATCHED"
    assert result.repair_dispatched is True
    assert result.pull_request == 7
    dispatch = next(call for call in calls if call[0] == "POST")
    payload = dispatch[2]
    assert payload is not None
    assert payload["ref"] == "main"
    inputs = payload["inputs"]
    assert inputs["scope"] == "pull_request"
    assert inputs["target_sha"] == "abc123"
    assert inputs["source_name"] == "CodeQL"
    assert "without suppressing" in inputs["failure_summary"]
    assert "installation-token" not in str(result.as_dict())


def test_second_level_codeql_gate_run_does_not_duplicate_original_dispatch() -> None:
    result = bridge_security_failure(
        repository="owner/repo",
        event=event(workflow="Amosclaud CodeQL Threat Gate"),
        connection=connection(),
        request=lambda *args: (_ for _ in ()).throw(AssertionError(args)),
    )

    assert result.status == "NOT_APPLICABLE"
    assert result.repair_dispatched is False


def test_stale_security_result_never_dispatches_repair() -> None:
    calls: list[tuple[str, str]] = []

    def request(method, url, headers, payload):
        calls.append((method, url))
        if url.endswith("/pulls/7"):
            return 200, {"state": "open", "head": {"sha": "new-head"}}
        raise AssertionError((method, url, payload))

    result = bridge_security_failure(
        repository="owner/repo",
        event=event(),
        connection=connection(),
        request=request,
    )

    assert result.status == "STALE_SECURITY_RESULT"
    assert result.repair_dispatched is False
    assert not any(method == "POST" for method, _ in calls)


def test_successful_security_run_does_not_dispatch() -> None:
    result = bridge_security_failure(
        repository="owner/repo",
        event=event(conclusion="success"),
        connection=connection(),
        request=lambda *args: (_ for _ in ()).throw(AssertionError(args)),
    )

    assert result.status == "NOT_APPLICABLE"
    assert result.repair_dispatched is False


def test_unapproved_workflow_does_not_gain_repair_authority() -> None:
    result = bridge_security_failure(
        repository="owner/repo",
        event=event(workflow="Untrusted Workflow"),
        connection=connection(),
        request=lambda *args: (_ for _ in ()).throw(AssertionError(args)),
    )

    assert result.status == "NOT_APPLICABLE"
    assert result.repair_dispatched is False


def test_pull_request_can_be_resolved_from_exact_commit() -> None:
    calls: list[tuple[str, str, dict[str, Any] | None]] = []

    def request(method, url, headers, payload):
        calls.append((method, url, payload))
        if "/commits/abc123/pulls" in url:
            return 200, [{"number": 8, "state": "open"}]
        if url.endswith("/pulls/8"):
            return 200, {"state": "open", "head": {"sha": "abc123"}}
        if url.endswith("/amosclaud-repair-control-plane.yml/dispatches"):
            return 204, {}
        raise AssertionError((method, url, payload))

    result = bridge_security_failure(
        repository="owner/repo",
        event=event(pull_number=None),
        connection=connection(),
        request=request,
    )

    assert result.status == "REPAIR_DISPATCHED"
    assert result.pull_request == 8


def test_dispatch_api_failure_blocks_instead_of_claiming_repair() -> None:
    def request(method, url, headers, payload):
        if url.endswith("/pulls/7"):
            return 200, {"state": "open", "head": {"sha": "abc123"}}
        if url.endswith("/amosclaud-repair-control-plane.yml/dispatches"):
            return 403, {}
        raise AssertionError((method, url, payload))

    result = bridge_security_failure(
        repository="owner/repo",
        event=event(),
        connection=connection(),
        request=request,
    )

    assert result.status == "BLOCKED"
    assert result.exit_code == 1
    assert result.repair_dispatched is False
    assert "403" in result.detail

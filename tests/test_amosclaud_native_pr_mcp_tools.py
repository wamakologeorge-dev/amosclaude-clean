from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from amoscloud_ai.connectors.amosclaud_account.native_pr_tools import (
    _body_or_raise,
    register_native_pr_tools,
)


@dataclass
class FakeMCP:
    tools: dict[str, Any] = field(default_factory=dict)

    def tool(self, *, annotations=None):
        del annotations

        def decorator(function):
            self.tools[function.__name__] = function
            return function

        return decorator


def _register(request):
    mcp = FakeMCP()

    def require(_ctx, scope):
        assert scope in {"repositories:read", "repositories:write"}
        return 7, {}

    register_native_pr_tools(
        mcp=mcp,
        require_scope=require,
        request_as_user=request,
        read_annotations=None,
        write_annotations=None,
    )
    return mcp


def test_registers_first_class_native_pr_and_action_products():
    async def request(**_kwargs):
        return {"ok": True, "status_code": 200, "body": {}}

    mcp = _register(request)
    assert set(mcp.tools) == {
        "amosclaud_list_repositories",
        "amosclaud_create_pull_request",
        "amosclaud_list_pull_requests",
        "amosclaud_get_pull_request",
        "amosclaud_run_pull_request_checks",
        "amosclaud_get_pull_request_checks",
        "amosclaud_control_pull_request",
        "amosclaud_merge_pull_request",
    }


def test_body_or_raise_preserves_amosclaud_failure_evidence():
    assert _body_or_raise(
        {"ok": True, "status_code": 201, "body": {"id": 3}},
        operation="Create pull request",
    ) == {"id": 3}

    with pytest.raises(RuntimeError, match="409") as exc:
        _body_or_raise(
            {
                "ok": False,
                "status_code": 409,
                "body": {"detail": "Action checks are not green"},
            },
            operation="Merge pull request",
        )
    assert "Action checks are not green" in str(exc.value)


@pytest.mark.asyncio
async def test_create_pull_request_routes_only_through_amosclaud_native_api():
    calls: list[dict[str, Any]] = []

    async def request(**kwargs):
        calls.append(kwargs)
        return {
            "ok": True,
            "status_code": 201,
            "body": {"id": 11, "state": "open", "head_branch": "work/mcp"},
        }

    mcp = _register(request)
    result = await mcp.tools["amosclaud_create_pull_request"](
        repository_id=4,
        title="Move development to Amosclaud",
        head_branch="work/mcp",
        base_branch="main",
        body="Native Amosclaud PR",
        ctx=object(),
    )

    assert result["authority"] == "amosclaud"
    assert result["pull_request"]["id"] == 11
    assert calls == [
        {
            "user_id": 7,
            "method": "POST",
            "path": "/api/v1/repositories/4/pull-requests",
            "body": {
                "title": "Move development to Amosclaud",
                "body": "Native Amosclaud PR",
                "head_branch": "work/mcp",
                "base_branch": "main",
            },
        }
    ]


@pytest.mark.asyncio
async def test_merge_tool_uses_verified_amosclaud_production_gate():
    calls: list[dict[str, Any]] = []

    async def request(**kwargs):
        calls.append(kwargs)
        return {
            "ok": True,
            "status_code": 200,
            "body": {"state": "merged", "merge_commit": "abc123"},
        }

    mcp = _register(request)
    result = await mcp.tools["amosclaud_merge_pull_request"](
        repository_id=4,
        pull_request_id=11,
        ctx=object(),
    )

    assert result["authority"] == "amosclaud"
    assert result["authoritative"] is True
    assert calls[0]["path"] == (
        "/api/v1/amosclaud/production/repositories/4/pull-requests/11/action"
    )
    assert calls[0]["body"] == {"action": "merge"}

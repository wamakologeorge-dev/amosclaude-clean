"""End-to-end contract for the Amosclaud Autonomous engineering agent.

This file intentionally gathers the platform's required public surfaces in one
place. Focused unit tests may still live elsewhere, but a release must satisfy
this complete Autonomous contract before it is considered ready.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from amoscloud_ai.main import create_app
from amoscloud_ai.verification import verification_contract


REQUIRED_ROUTE_PATHS = {
    "/api/v1/agent",
    "/api/v1/agent/readiness",
    "/api/v1/agent/run",
    "/api/v1/pipelines/{pipeline_id}",
    "/api/v1/amomodel/status",
    "/api/v1/server/cb/amosclaud",
    "/api/v1/agent-chain/metadata",
    "/api/v1/autonomous/server/api/cb/router/byte/metadata",
    "/api/v1/codex/system-bundle/preview",
    "/api/v1/connections/preflight",
    "/control-bus",
    "/v1/models",
    "/v1/chat/completions",
}

DASHBOARD_REQUIRED_MARKERS = {
    'data-amosclaud-head="true"',
    'id="btn-check-agent-connections"',
    'id="btn-amomodel-on"',
    'id="btn-amomodel-off"',
    'id="agent-connection-status"',
    'href="/bundles"',
    'src="/static/agent-control.js"',
    'src="/static/conversational-agent.js"',
    'src="/static/single-autonomous-dock.js"',
}


def route_paths() -> set[str]:
    return {
        str(getattr(route, "path", ""))
        for route in create_app().routes
        if getattr(route, "path", None)
    }


def test_all_required_autonomous_routes_are_registered() -> None:
    paths = route_paths()
    missing = sorted(REQUIRED_ROUTE_PATHS - paths)
    assert not missing, "Missing Amosclaud Autonomous routes:\n" + "\n".join(missing)


@pytest.mark.parametrize("path", sorted(REQUIRED_ROUTE_PATHS))
def test_each_required_route_is_unique(path: str) -> None:
    matches = [
        route
        for route in create_app().routes
        if str(getattr(route, "path", "")) == path
    ]
    assert len(matches) == 1, f"Expected exactly one registered route for {path}, found {len(matches)}"


def test_autonomous_dashboard_contains_required_controls() -> None:
    source = Path("web/index.html").read_text(encoding="utf-8")
    missing = sorted(marker for marker in DASHBOARD_REQUIRED_MARKERS if marker not in source)
    assert not missing, "Missing Autonomous dashboard markers:\n" + "\n".join(missing)


def test_autonomous_dashboard_declares_owner_permission_and_evidence() -> None:
    source = Path("web/index.html").read_text(encoding="utf-8").lower()
    for phrase in ("instructions", "owner permission", "verification evidence", "final result"):
        assert phrase in source


def test_engineering_work_cannot_complete_without_verification() -> None:
    pending = verification_contract(engineering=True)
    failed = verification_contract(
        engineering=True,
        report={"status": "failed", "verification_id": "verification-1"},
    )
    passed = verification_contract(
        engineering=True,
        report={"status": "passed", "verification_id": "verification-2"},
    )

    assert pending == {"required": True, "status": "pending", "verified": False}
    assert failed["required"] is True
    assert failed["verified"] is False
    assert passed["required"] is True
    assert passed["verified"] is True


def test_non_engineering_guidance_does_not_require_build_evidence() -> None:
    result = verification_contract(engineering=False)
    assert result["required"] is False
    assert result["status"] == "not-applicable"
    assert result["verified"] is True


def test_autonomous_uses_only_the_canonical_public_domain() -> None:
    canonical_url = "http://www.amosclaud.com/"
    canonical_host = "www.amosclaud.com"

    assert canonical_url in Path("docs/DOMAIN_OWNERSHIP.md").read_text(encoding="utf-8")
    assert Path("CNAME").read_text(encoding="utf-8").strip() == canonical_host


def test_agent_control_script_is_present() -> None:
    script = Path("web/agent-control.js")
    assert script.is_file(), "web/agent-control.js must exist for dashboard controls"
    assert script.read_text(encoding="utf-8").strip(), "web/agent-control.js must not be empty"

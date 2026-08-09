"""Contracts for repository Chat and Autonomous visibility on mobile."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"


def test_workspace_exposes_chat_and_autonomous_as_primary_tabs() -> None:
    html = (WEB / "workspace.html").read_text(encoding="utf-8")

    assert 'data-tab="chat"' in html
    assert 'data-panel="chat"' in html
    assert 'id="ws-chat-form"' in html
    assert 'id="ws-chat-input"' in html
    assert 'data-tab="autonomous"' in html
    assert 'data-panel="autonomous"' in html
    assert 'data-open-workspace-tab="chat"' in html
    assert 'data-open-workspace-tab="autonomous"' in html
    assert "/static/workspace-chat.css" in html
    assert "/static/workspace-chat.js" in html


def test_repository_chat_uses_shared_chat_api_with_repository_context() -> None:
    source = (WEB / "workspace-chat.js").read_text(encoding="utf-8")

    assert "fetch('/api/chat'" in source
    assert "Repository context:" in source
    assert "Repository ID:" in source
    assert "Selected branch:" in source
    assert "sessionStorage" in source
    assert "data-open-workspace-tab" in source
    assert "activateWorkspaceTab" in source


def test_repository_chat_bounds_network_wait_and_reports_api_outages() -> None:
    source = (WEB / "workspace-chat.js").read_text(encoding="utf-8")

    assert "const chatTimeoutMs = 57000" in source
    assert "new AbortController()" in source
    assert "signal: controller.signal" in source
    assert "const rawBody = await response.text()" in source
    assert "response.headers.get('content-type')" in source
    assert "JSON.parse(rawBody)" in source
    assert "response.json()" not in source
    assert "clearTimeout(timeout)" in source
    assert "Chat request timed out" in source
    assert "/api/chat could not be reached" in source
    assert "/health endpoint" in source


def test_repository_chat_disables_all_prompt_controls_while_busy() -> None:
    source = (WEB / "workspace-chat.js").read_text(encoding="utf-8")

    assert "const promptButtons = Array.from" in source
    assert "promptButtons.forEach" in source
    assert "button.disabled = busy" in source


def test_mobile_repository_navigation_is_fixed_and_visible() -> None:
    css = (WEB / "workspace-chat.css").read_text(encoding="utf-8")

    assert "position:fixed!important" in css
    assert "top:auto!important" in css
    assert "bottom:0" in css
    assert ".ws-mobile-primary-actions" in css
    assert "grid-template-columns:1fr 1fr" in css


def test_workspace_drawer_settings_buttons_activate_and_close_drawer() -> None:
    html = (WEB / "workspace.html").read_text(encoding="utf-8")
    source = (WEB / "workspace-chat.js").read_text(encoding="utf-8")

    assert 'data-open-tab="chat"' in html
    assert 'data-open-tab="autonomous"' in html
    assert "data-open-tab" in source
    assert "account-drawer" in source


def test_autonomous_buttons_remain_connected_to_real_controls() -> None:
    html = (WEB / "workspace.html").read_text(encoding="utf-8")
    source = (WEB / "workspace.js").read_text(encoding="utf-8")

    for control in (
        'id="ws-agent-build"',
        'id="ws-agent-test"',
        'id="ws-agent-review"',
        'id="ws-agent-deploy"',
    ):
        assert control in html

    assert "ws-agent-build" in source
    assert "ws-agent-test" in source
    assert "ws-agent-review" in source
    assert "ws-agent-deploy" in source
    assert "/api/v1/agent/run" in source

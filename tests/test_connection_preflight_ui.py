from pathlib import Path


def test_legacy_workspace_exposes_autonomous_runtime_health_controls():
    """The legacy runtime-health hub is preserved at /cloud/agent/legacy."""
    root = Path(__file__).resolve().parents[1]
    source = (root / "amoscloud_ai" / "main.py").read_text(encoding="utf-8")
    legacy = source.split('@app.get("/cloud/agent/legacy"', 1)[1]
    legacy = legacy.split('@app.get("/"', 1)[0]
    html = (root / "web" / "index.html").read_text(encoding="utf-8")
    script = (root / "web" / "agent-control.js").read_text(encoding="utf-8")

    assert 'return FileResponse(web_dir / "index.html")' in legacy
    assert 'id="btn-check-agent-connections"' in html
    assert 'id="agent-connection-status"' in html
    assert "Runtime health" in html
    assert "Check Autonomous and server" in html
    assert "/health" in script
    assert "/api/v1/agent" in script
    assert "/api/v1/pipelines/" in script
    assert "Agent plan" in script
    assert "platform-autonomous-chat" in script
    assert 'data-agent-suggestion="Inspect' in html
    assert "Task received" in script
    assert "Task is executing" in script
    assert "Verified evidence recorded" in script


def test_primary_workspace_exposes_an_honest_runtime_status_panel():
    """The primary page explains runtime problems instead of toggling power."""
    root = Path(__file__).resolve().parents[1]
    html = (root / "web" / "command-center.html").read_text(encoding="utf-8")
    script = (root / "web" / "command-center.js").read_text(encoding="utf-8")

    assert "Runtime status" in html
    assert 'id="runtime-remediation"' in html
    assert 'id="runtime-provider"' in html
    assert "/ready" in script
    assert "AmosclaudRuntimeStatus" in script
    assert "Check Autonomous and server" not in html

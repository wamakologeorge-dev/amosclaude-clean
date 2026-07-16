from pathlib import Path


def test_workspace_exposes_autonomous_runtime_health_controls():
    root = Path(__file__).resolve().parents[1]
    html = (root / "web" / "index.html").read_text(encoding="utf-8")
    script = (root / "web" / "agent-control.js").read_text(encoding="utf-8")

    assert 'id="btn-check-agent-connections"' in html
    assert 'id="agent-connection-status"' in html
    assert "Runtime health" in html
    assert "Check Autonomous and server" in html
    assert "/health" in script
    assert "/api/v1/agent" in script
    assert "/api/v1/pipelines/" in script
    assert "Autonomous execution console" in script
    assert "Task received" in script
    assert "Task is executing" in script
    assert "Verified evidence recorded" in script

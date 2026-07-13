from pathlib import Path


def test_workspace_exposes_connection_preflight_controls():
    root = Path(__file__).resolve().parents[1]
    html = (root / "web" / "index.html").read_text(encoding="utf-8")
    script = (root / "web" / "agent-control.js").read_text(encoding="utf-8")

    assert 'id="btn-check-agent-connections"' in html
    assert 'id="agent-connection-status"' in html
    assert "/api/v1/agent/github/preflight" in script
    assert "GitHub ready" in script
    assert "Model ready" in script

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "web" / "index.html"
RUNTIME = ROOT / "web" / "unified-agent-runtime.js"


def test_platform_presents_one_professional_operator() -> None:
    html = INDEX.read_text(encoding="utf-8")
    assert "Amosclaud Operator" in html
    assert "Amosclaud-bot" in html
    assert "Codex-style planning" in html
    assert "Amosclaud Autonomous execution" in html
    assert "Amosclaud Fixer verification" in html
    assert 'src="/static/unified-agent-runtime.js"' in html
    assert html.index("unified-agent-runtime.js") < html.index("agent-control.js")


def test_engineering_requests_use_unified_agent_and_verification() -> None:
    source = RUNTIME.read_text(encoding="utf-8")
    assert "amosclaud-platform-unified-operator" in source
    assert "operator: 'amosclaud-bot'" in source
    assert "planner: 'codex-style'" in source
    assert "repair_engine: 'amosclaud-fixer'" in source
    assert "use_agent: actionRequested" in source
    assert "apply_changes: actionRequested" in source
    assert "require_verification: true" in source
    assert "return_evidence: true" in source

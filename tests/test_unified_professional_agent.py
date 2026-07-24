from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "web" / "index.html"
RUNTIME = ROOT / "web" / "unified-agent-runtime.js"
EXECUTOR = ROOT / "amosclaud_os" / "agent" / "executor.py"


def test_platform_presents_one_truthful_engineering_operator() -> None:
    html = INDEX.read_text(encoding="utf-8")
    assert "Amosclaud Agent" in html
    assert "Real native execution is active" in html
    assert "Native repository actions do not require a model key" in html
    assert "returns a clear blocker instead of pretending" in html
    assert 'src="/static/unified-agent-runtime.js"' in html
    assert html.index("unified-agent-runtime.js") < html.index("agent-control.js")


def test_engineering_requests_use_native_executor_and_verification() -> None:
    source = RUNTIME.read_text(encoding="utf-8")
    assert "/api/v1/core/os/execute" in source
    assert "amosclaud-os-command-surface" in source
    assert "execution_contract: 'native-or-truthful-blocker'" in source
    assert "require_verification: true" in source
    assert "return_evidence: true" in source
    assert "planner: 'codex-style'" not in source


def test_native_executor_never_substitutes_platform_source() -> None:
    source = EXECUTOR.read_text(encoding="utf-8")
    assert "The platform did not run against its own application source as a substitute" in source
    assert "No native Amosclaud repository is selected" in source
    assert "AMOSCLAUD_MODEL_ENDPOINT or AMOSCLAUD_MODEL_URL" in source

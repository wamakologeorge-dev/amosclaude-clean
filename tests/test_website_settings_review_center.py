from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "pages-site" / "index.html"
SCRIPT = ROOT / "pages-site" / "settings-review-center.js"
STYLE = ROOT / "pages-site" / "settings-review-center.css"


def test_settings_and_review_assets_are_deployed() -> None:
    index = INDEX.read_text(encoding="utf-8")
    assert "settings-review-center.css" in index
    assert "settings-review-center.js" in index
    assert 'href="#review-center"' in index


def test_top_left_settings_explains_real_capabilities() -> None:
    script = SCRIPT.read_text(encoding="utf-8")
    style = STYLE.read_text(encoding="utf-8")
    assert "Open Amosclaud settings" in script
    assert "Truth and evidence" in script
    assert "Unknown results" in script
    assert "Never displayed as PASS" in script
    assert "Direct private-repository writes" in script
    assert ".settings-button" in style
    assert "top:1rem" in style
    assert "left:1rem" in style


def test_review_center_uses_github_evidence_and_required_actions() -> None:
    script = SCRIPT.read_text(encoding="utf-8")
    assert "/actions/runs?per_page=12" in script
    assert "/issues?state=open&per_page=30" in script
    assert "/pulls?state=open&per_page=20" in script
    assert "approval required|amosclaud approval" in script
    assert "GitHub returned a successful completed check" in script
    assert "GitHub check requires diagnosis or repair" in script
    assert "Review data unavailable" in script


def test_chat_prepares_governed_command_without_false_execution_claim() -> None:
    script = SCRIPT.read_text(encoding="utf-8")
    assert "Chat with Amosclaud Bot" in script
    assert "prepareCommandFromChat" in script
    assert "request-type" in script
    assert "request-title" in script
    assert "request-body" in script
    assert "Prepared a ${action.toUpperCase()} command card" in script
    assert "does not silently write to GitHub" in script
    assert "localStorage" not in script
    assert "sessionStorage" not in script
    assert "github_pat_" not in script
    assert "ghp_" not in script

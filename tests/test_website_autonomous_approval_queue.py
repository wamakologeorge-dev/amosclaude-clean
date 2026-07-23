from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "pages-site" / "index.html"
SCRIPT = ROOT / "pages-site" / "autonomous-approval-queue.js"
STYLE = ROOT / "pages-site" / "autonomous-approval-queue.css"


def test_approval_queue_assets_are_deployed() -> None:
    index = INDEX.read_text(encoding="utf-8")
    assert "autonomous-approval-queue.css" in index
    assert "autonomous-approval-queue.js" in index
    assert 'href="#autonomous-approval-queue"' in index
    assert "Review approvals" in index


def test_queue_reads_real_errors_and_approval_records() -> None:
    script = SCRIPT.read_text(encoding="utf-8")
    assert "wamakologeorge-dev/amosclaude-clean" in script
    assert "wamakologeorge-dev/Amosclaud1" in script
    assert "/issues?state=open&per_page=50" in script
    assert "/actions/runs?per_page=40" in script
    assert "latestRunsOnly" in script
    assert "approval required|amosclaud approval|autonomous approval" in script


def test_queue_numbers_cards_and_offers_single_use_decisions() -> None:
    script = SCRIPT.read_text(encoding="utf-8")
    assert "formatNumber" in script
    assert 'padStart(3, "0")' in script
    assert "Approve once" in script
    assert "Deny" in script
    assert "single_use: true" in script
    assert "Single-use for this exact record" in script


def test_static_page_never_claims_unrecorded_approval() -> None:
    script = SCRIPT.read_text(encoding="utf-8")
    assert "APPROVED was not recorded" in script
    assert "DENIED was not recorded" in script
    assert "secure Amosclaud Control API" in script
    assert "/api/v1/approvals/decision" in script
    assert "result.recorded !== true" in script


def test_queue_remains_token_free_and_safe() -> None:
    script = SCRIPT.read_text(encoding="utf-8")
    assert "localStorage" not in script
    assert "sessionStorage" not in script
    assert "github_pat_" not in script
    assert "ghp_" not in script
    assert "innerHTML" not in script
    assert "textContent" in script
    assert "content-type" in script.lower()


def test_queue_is_mobile_responsive() -> None:
    style = STYLE.read_text(encoding="utf-8")
    assert ".autonomous-approval-queue" in style
    assert ".autonomous-approval-card" in style
    assert "@media(max-width:800px)" in style

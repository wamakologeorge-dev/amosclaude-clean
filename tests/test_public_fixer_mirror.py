from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "pages-site" / "index.html"
SCRIPT = ROOT / "pages-site" / "public-fixer-mirror.js"
STYLE = ROOT / "pages-site" / "public-fixer-mirror.css"


def test_landing_page_loads_public_fixer_mirror_assets() -> None:
    index = INDEX.read_text(encoding="utf-8")
    assert "public-fixer-mirror.css" in index
    assert "public-fixer-mirror.js" in index
    assert '#public-fixer-mirror' in index
    assert "Watch public processing" in index


def test_public_fixer_mirror_uses_first_party_github_evidence() -> None:
    script = SCRIPT.read_text(encoding="utf-8")
    assert "wamakologeorge-dev/Amosclaud1" in script
    assert "wamakologeorge-dev/amosclaude-clean" in script
    assert "/issues?state=all" in script
    assert "/comments?per_page=100" in script
    assert "/actions/runs?per_page=20" in script
    assert "Open first-party evidence" in script
    assert "No result is manufactured" in script


def test_public_fixer_mirror_shows_real_processing_lifecycle() -> None:
    script = SCRIPT.read_text(encoding="utf-8")
    for stage in ("ANALYZE", "PLAN", "EDIT", "TEST", "VERIFY", "PUBLISH"):
        assert stage in script
    for field in ("Target", "Request", "Current evidence", "Publication", "Changed files", "Updated"):
        assert field in script
    assert "VERIFICATION FAILED" in script
    assert "ROLLED_BACK" not in script or "rolled_back" in script


def test_public_fixer_mirror_remains_token_free_and_safe() -> None:
    script = SCRIPT.read_text(encoding="utf-8")
    assert "localStorage" not in script
    assert "sessionStorage" not in script
    assert "github_pat_" not in script
    assert "ghp_" not in script
    assert "innerHTML" not in script
    assert "textContent" in script


def test_public_fixer_mirror_is_mobile_responsive() -> None:
    style = STYLE.read_text(encoding="utf-8")
    assert ".public-fixer-mirror" in style
    assert ".fixer-mirror-card" in style
    assert "@media(max-width:800px)" in style

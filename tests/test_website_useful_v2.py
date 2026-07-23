from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "pages-site" / "index.html"
SCRIPT = ROOT / "pages-site" / "control-plane-enhancements.js"
STYLE = ROOT / "pages-site" / "control-plane-enhancements.css"


def test_useful_control_plane_assets_are_loaded() -> None:
    index = INDEX.read_text(encoding="utf-8")
    assert "control-plane-enhancements.css" in index
    assert "control-plane-enhancements.js" in index
    assert "Analyze" in index
    assert "Publish" in index


def test_control_plane_supports_search_filters_refresh_and_public_preview() -> None:
    script = SCRIPT.read_text(encoding="utf-8")
    for expected in (
        "workspace-search",
        "workspace-filter",
        "refresh-control-plane",
        "repository-preview",
        "Preview public repository",
        "api.github.com/repos/",
        "inspect",
        "health",
        "verify",
    ):
        assert expected in script


def test_enhancement_remains_token_free_and_safe() -> None:
    script = SCRIPT.read_text(encoding="utf-8")
    assert "localStorage" not in script
    assert "sessionStorage" not in script
    assert "github_pat_" not in script
    assert "ghp_" not in script
    assert "innerHTML" not in script
    assert "textContent" in script


def test_mobile_styles_exist_for_new_controls() -> None:
    style = STYLE.read_text(encoding="utf-8")
    assert "control-tools-grid" in style
    assert "repository-preview-control" in style
    assert "@media(max-width:650px)" in style

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "pages-site" / "index.html"
CONTROL_PLANE = ROOT / "pages-site" / "control-plane.js"


def test_control_plane_is_loaded_by_the_agent_hub() -> None:
    index = INDEX.read_text(encoding="utf-8")
    assert 'id="control-plane"' not in index  # injected once by the controller
    assert 'href="#control-plane"' in index
    assert 'src="./control-plane.js"' in index
    assert "Send through Amosclaud1" in index


def test_control_plane_embeds_project_work_without_collecting_tokens() -> None:
    source = CONTROL_PLANE.read_text(encoding="utf-8")
    assert "wamakologeorge-dev/amosclaude-clean" in source
    assert "wamakologeorge-dev/Amosclaud1" in source
    assert "/issues?state=open" in source
    assert "/pulls?state=open" in source
    assert "/actions/runs" in source
    assert "approval required" in source.lower()
    assert "commandFor" in source
    assert "localStorage" not in source
    assert "sessionStorage" not in source
    assert "github_pat_" not in source
    assert "ghp_" not in source


def test_control_plane_uses_safe_dom_rendering_for_github_content() -> None:
    source = CONTROL_PLANE.read_text(encoding="utf-8")
    assert "textContent" in source
    assert "createElement" in source
    assert "innerHTML" not in source

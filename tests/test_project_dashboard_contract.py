from pathlib import Path


def test_projects_dashboard_uses_real_project_apis() -> None:
    root = Path(__file__).resolve().parents[1]
    html = (root / "web" / "projects.html").read_text(encoding="utf-8")
    script = (root / "web" / "projects.js").read_text(encoding="utf-8")

    assert "Create real issue" in html
    assert "/api/v1/projects" in script
    assert "/issues" in script
    assert "/results" in script
    assert "start_work" in script
    assert "Amosclaud-bot" in script


def test_repository_page_links_to_projects_dashboard() -> None:
    root = Path(__file__).resolve().parents[1]
    html = (root / "web" / "repositories.html").read_text(encoding="utf-8")
    assert "/static/projects.html" in html

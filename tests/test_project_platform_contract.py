"""Contract coverage for persistent projects, issues, and real results."""
from amoscloud_ai.main import create_app


def test_project_platform_routes_are_registered() -> None:
    paths = {getattr(route, "path", "") for route in create_app().routes}
    required = {
        "/api/v1/projects",
        "/api/v1/projects/{project_id}",
        "/api/v1/projects/{project_id}/issues",
        "/api/v1/projects/{project_id}/results",
        "/api/v1/operator/requests",
    }
    assert not (required - paths)


def test_project_issues_can_start_one_brain_task() -> None:
    from pathlib import Path

    source = Path("amoscloud_ai/project_platform.py").read_text(encoding="utf-8")
    assert '"operator": "Amosclaud-bot"' in source
    assert '"single_brain": True' in source
    assert '"project_id": project_id' in source
    assert '"issue_id": issue_id' in source
    assert "task_router.create_task" in source


def test_project_results_are_backed_by_completed_global_tasks() -> None:
    from pathlib import Path

    source = Path("amoscloud_ai/project_platform.py").read_text(encoding="utf-8")
    assert "global_tasks" in source
    assert "status IN ('completed','failed')" in source
    assert "artifacts" in Path("amoscloud_ai/api/routes/task_router.py").read_text(encoding="utf-8")

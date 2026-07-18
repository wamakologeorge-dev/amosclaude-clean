from amoscloud_ai.api.routes import repository_templates
from amoscloud_ai.api.routes.real_repositories import CI_WORKFLOW, RealRepositoryCreate


def test_real_repository_routes_are_mounted_under_repository_api():
    paths = {route.path for route in repository_templates.router.routes}
    assert "/repositories/create-real" in paths
    assert "/repositories/{repository_id}/real-status" in paths


def test_real_repository_defaults_enable_working_project_basics():
    request = RealRepositoryCreate(name="real-project")
    assert request.initialize_readme is True
    assert request.initialize_gitignore is True
    assert request.visibility == "private"


def test_generated_ci_runs_real_project_commands_and_has_fallback():
    assert "python -m compileall ." in CI_WORKFLOW
    assert "python -m pytest -q" in CI_WORKFLOW
    assert "npm test --if-present" in CI_WORKFLOW
    assert "npm run build --if-present" in CI_WORKFLOW
    assert "Repository contains committed project files." in CI_WORKFLOW

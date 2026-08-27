from __future__ import annotations

from pathlib import Path

from amoscloud_ai import first_production

ROOT = Path(__file__).resolve().parents[1]
ROUTE = ROOT / "amoscloud_ai" / "api" / "routes" / "amosclaud_production.py"
APP = ROOT / "amoscloud_ai" / "first_production_app.py"
CONFIG = ROOT / ".amosclaud" / "first-production.json"
DOC = ROOT / "docs" / "AMOSCLAUD_FIRST_PRODUCTION.md"


def test_ci_colors_are_product_truth_not_provider_truth() -> None:
    assert first_production.ci_color("success") == "green"
    assert first_production.ci_color("failed") == "red"
    assert first_production.ci_color("running") == "amber"
    assert first_production.ci_color(None) == "gray"


def test_merge_requires_green_ci_for_exact_head_sha() -> None:
    assert first_production.merge_allowed(
        ci_status="success", head_sha="abc", verified_sha="abc"
    )
    assert not first_production.merge_allowed(
        ci_status="success", head_sha="new", verified_sha="old"
    )
    assert not first_production.merge_allowed(
        ci_status="failed", head_sha="abc", verified_sha="abc"
    )
    assert not first_production.merge_allowed(
        ci_status=None, head_sha="abc", verified_sha=None
    )


def test_external_provider_failure_does_not_change_amosclaud_ci_color() -> None:
    truth = first_production.production_truth(
        ci_status="success",
        head_sha="abc",
        verified_sha="abc",
        external={"github": "failure", "railway": "failure", "vercel": "failure"},
    )
    assert truth["ci"]["color"] == "green"
    assert truth["merge_allowed"] is True
    assert truth["external_providers"]["github"]["authoritative"] is False
    assert truth["external_providers"]["railway"]["blocks_amosclaud_merge"] is False


def test_true_false_contract_is_explicit() -> None:
    matrix = first_production.capability_matrix()
    assert matrix["amosclaud_is_production_authority"] is True
    assert matrix["native_issues"] is True
    assert matrix["native_pull_requests"] is True
    assert matrix["amosclaud_ci_green_red_truth"] is True
    assert matrix["railway_required_for_production_truth"] is False
    assert matrix["github_required_for_native_repository_workflow"] is False
    assert matrix["domain_name_runs_compute_by_itself"] is False
    assert matrix["vercel_serverless_local_sqlite_is_durable"] is False


def test_control_api_has_all_requested_pr_actions_and_ci_gate() -> None:
    source = ROUTE.read_text(encoding="utf-8")
    for action in ("close", "reopen", "delete", "restore", "merge", "unmerge"):
        assert f'"{action}"' in source
    assert "Amosclaud CI must be green for the exact pull-request head before merge" in source
    assert 'trigger="amosclaud-ci"' in source
    assert '"authoritative": True' in source


def test_first_production_entrypoint_precedes_existing_platform() -> None:
    source = APP.read_text(encoding="utf-8")
    assert "app.include_router(production_router, prefix=\"/api/v1\")" in source
    assert "app.mount(\"/\", connected_production_app" in source
    assert source.index("app.include_router") < source.index("app.mount")


def test_configuration_and_documentation_state_provider_boundaries() -> None:
    config = CONFIG.read_text(encoding="utf-8")
    doc = DOC.read_text(encoding="utf-8")
    assert '"require_railway_health": false' in config
    assert '"require_github_checks": false' in config
    assert '"require_green_amosclaud_ci": true' in config
    assert "Vercel serverless local SQLite is durable production storage | FALSE" in doc
    assert "Amosclaud is the production authority" in doc

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app.py"
DEPLOYMENT_EXECUTOR = ROOT / "deployment_worker" / "executor.py"
PROGRAM = ROOT / "docs" / "ABSOLUTE_SECURITY_HARDENING.md"


def test_dashboard_routes_require_authentication_and_owner_scope() -> None:
    source = APP.read_text(encoding="utf-8")

    assert "Depends(require_user)" in source
    assert source.count("owner_user_id") >= 20
    assert "WHERE id=? AND owner_user_id=?" in source
    assert "Authentication required" in source


def test_dashboard_never_mounts_an_unauthenticated_artifact_directory() -> None:
    source = APP.read_text(encoding="utf-8")

    assert 'app.mount("/artifacts"' not in source
    assert '@app.get("/artifacts/{run_id}/{artifact_path:path}")' in source
    assert "owner_user_id=? AND relative_path=?" in source


def test_dashboard_execution_is_queued_and_not_run_in_api_process() -> None:
    source = APP.read_text(encoding="utf-8")

    assert "dispatch_task(run_dashboard_project, run_id, owner)" in source
    assert "status='running'" in source
    assert "shell=True" not in source
    assert "subprocess.run" not in source


def test_secret_and_domain_tokens_are_not_in_normal_project_responses() -> None:
    source = APP.read_text(encoding="utf-8")
    project_dict = source.split("def project_dict", 1)[1].split(
        "def _public_run", 1
    )[0]

    assert '"domain_token"' not in project_dict
    assert '"value": "••••••••"' in source
    assert "redact_output" not in source  # Redaction is centralized in the runner.


def test_legacy_deployment_worker_does_not_execute_host_shell_commands() -> None:
    source = DEPLOYMENT_EXECUTOR.read_text(encoding="utf-8")

    assert "shell=True" not in source
    assert "run_in_isolated_container" in source
    assert "dedicated Amosclaud preview service" in source


def test_security_program_keeps_high_risk_approval_command() -> None:
    text = PROGRAM.read_text(encoding="utf-8")

    assert "@amosclaud approve" in text
    assert "single-use" in text
    assert "OWNER, MEMBER, or COLLABORATOR" in text

from app.models.models import (
    AgentMode,
    AutonomousAgentRunRequest,
    AutonomousAgentRunResponse,
    DeploymentConfig,
    DeploymentEnvironment,
    PipelineStatus,
    PipelineTrigger,
    VerificationStatus,
)


def test_agent_request_has_first_class_repository_context():
    request = AutonomousAgentRunRequest(
        mode="fix",
        objective="Repair failing route tests",
        repository_id=12,
        pull_request_id=434,
        branch="repair/routes",
        commit_sha="abc123",
        model_id="amosclaud-folder-v1",
    )

    assert request.mode is AgentMode.FIX
    assert request.repository_id == 12
    assert request.pull_request_id == 434
    assert request.model_id == "amosclaud-folder-v1"


def test_pipeline_trigger_preserves_repository_identity():
    trigger = PipelineTrigger(
        trigger="pull_request",
        repository_id=12,
        pull_request_id=434,
        branch="agent/full-repository-repair-2",
        commit_sha="abc123",
    )

    assert trigger.repository_id == 12
    assert trigger.pull_request_id == 434
    assert trigger.commit_sha == "abc123"


def test_agent_response_carries_verification_evidence():
    response = AutonomousAgentRunResponse(
        accepted=True,
        run_id="run-1",
        mode=AgentMode.FIX,
        objective="Repair failing route tests",
        reply="Patch verified",
        pipeline_id="pipeline-1",
        status=PipelineStatus.PASSED,
        repository_id=12,
        pull_request_id=434,
        commit_sha="abc123",
        verification_id="verify-1",
        verification_status=VerificationStatus.PASSED,
        changed_files=["app/models/models.py"],
        started_at="2026-07-19T20:00:00Z",
    )

    assert response.verification_status is VerificationStatus.PASSED
    assert response.changed_files == ["app/models/models.py"]


def test_deployment_uses_approved_profile_contract():
    config = DeploymentConfig(
        environment=DeploymentEnvironment.STAGING,
        deployment_profile_id="staging-default",
        repository_id=12,
        commit_sha="abc123",
    )

    assert config.deployment_profile_id == "staging-default"
    assert config.deploy_command is None

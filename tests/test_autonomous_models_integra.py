import pytest

from amoscloud_ai.autonomous_models_integra import (
    MODEL_JOBS,
    integration_manifest,
    jobs_for_agent,
    route_model_job,
)


def test_registry_contains_25_unique_model_jobs():
    assert len(MODEL_JOBS) == 25
    assert len({job.job_id for job in MODEL_JOBS}) == 25
    assert len({job.capability for job in MODEL_JOBS}) == 25


def test_every_job_connects_to_one_of_five_agent_stages():
    assert {job.agent_stage for job in MODEL_JOBS} == {
        "agent-1", "agent-2", "agent-3", "agent-4", "agent-5"
    }
    assert all(jobs_for_agent(f"agent-{index}") for index in range(1, 6))


def test_write_jobs_require_explicit_authorization():
    with pytest.raises(PermissionError):
        route_model_job("code-editing")
    assert route_model_job("code-editing", write_authorized=True).job_id == "model-job-14"


def test_manifest_connects_all_jobs_to_same_engines():
    manifest = integration_manifest()
    assert manifest["model_job_count"] == 25
    assert manifest["autonomous_engine"] == "autonomous-core-orchestrator"
    assert manifest["agent_engine"] == "amosclaud-five-agent-engine"
    assert manifest["policy"]["verified_output_only"] is True

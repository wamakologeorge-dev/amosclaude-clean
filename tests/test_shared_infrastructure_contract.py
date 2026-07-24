from pathlib import Path

from shared.runtime import REQUIRED_PLATFORM_ENV, ServiceName, platform_endpoints
from shared.statuses import ExecutionStatus
from shared.verification import VerificationEvidence


COMPOSE = Path("Infrastructure/docker-compose.yml").read_text(encoding="utf-8")


def test_compose_and_shared_runtime_use_the_same_services():
    endpoints = platform_endpoints()
    assert endpoints[ServiceName.PLATFORM].base_url == "http://amosclaud:8000"
    assert endpoints[ServiceName.MODEL].base_url == "http://model:8091"
    assert endpoints[ServiceName.CREDENTIAL_AUTHORITY].base_url == "http://credential-authority:8001"
    assert endpoints[ServiceName.METRICS].base_url == "http://metrics:9090"
    assert endpoints[ServiceName.REDIS].base_url == "redis://redis:6379/0"

    for service in ("amosclaud:", "model:", "credential-authority:", "metrics:", "redis:"):
        assert service in COMPOSE


def test_compose_exports_the_shared_platform_environment_contract():
    for name in REQUIRED_PLATFORM_ENV:
        assert f"{name}:" in COMPOSE, f"Docker Compose must define {name}"

    assert "AMOSCLAUD_AUTONOMOUS_ENABLED: \"true\"" in COMPOSE
    assert "AMOSCLAUD_FIXER_ENABLED: \"true\"" in COMPOSE
    assert "AMOSCLAUD_REQUIRE_VERIFICATION: \"true\"" in COMPOSE
    assert "AMOSCLAUD_PROTECT_DEFAULT_BRANCH: \"true\"" in COMPOSE


def test_compose_uses_persistent_isolated_storage():
    assert "REPOSITORY_STORAGE_PATH: /data/repositories" in COMPOSE
    assert "AMOSCLAUD_WORKSPACE: /data/workspaces" in COMPOSE
    assert "amosclaud-data:/data" in COMPOSE
    assert "amosclaud-model:/model" in COMPOSE
    assert "amosclaud-credentials:/credentials" in COMPOSE
    assert "amosclaud-metrics:/metrics-data" in COMPOSE
    assert "amosclaud-redis:/data" in COMPOSE


def test_compose_does_not_embed_secret_values():
    assert "AGENT_JWT_SECRET_KEY: ${AGENT_JWT_SECRET_KEY:" in COMPOSE
    assert "API_KEY_MANAGER_ADMIN_PASSWORD: ${API_KEY_MANAGER_ADMIN_PASSWORD:" in COMPOSE
    assert "OPENAI_API_KEY" not in COMPOSE


def test_success_claim_requires_real_verification_evidence():
    evidence = VerificationEvidence(
        verification_id="verify-1",
        status=ExecutionStatus.PASSED,
        commit_sha="a" * 40,
        checks=["pytest", "security-scan"],
    )
    evidence.assert_success_claim_allowed()


def test_unverified_success_claim_is_rejected():
    evidence = VerificationEvidence(
        verification_id="verify-2",
        status=ExecutionStatus.RUNNING,
        commit_sha="b" * 40,
        checks=["pytest"],
    )
    try:
        evidence.assert_success_claim_allowed()
    except ValueError as exc:
        assert "before verification passes" in str(exc)
    else:
        raise AssertionError("running work must not be reported as successful")

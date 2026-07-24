import pytest

from amoscloud_ai.agent.professional_reliability import (
    Evidence,
    EvidenceKind,
    Hypothesis,
    OperationEvent,
    OperationStatus,
    ProfessionalResponse,
    can_claim_success,
    rank_hypotheses,
    sanitize_for_public_research,
    validate_scope,
)


def test_secret_values_are_removed_before_public_research():
    sanitized, redactions = sanitize_for_public_research(
        "Request failed token=abc123 password=hunter2 Authorization: Bearer private-token"
    )

    assert "abc123" not in sanitized
    assert "hunter2" not in sanitized
    assert "private-token" not in sanitized
    assert sanitized.count("[REDACTED]") == 3
    assert redactions


def test_scope_blocks_unrelated_resource():
    allowed, reason = validate_scope(
        active_objective="repair repository tests",
        requested_resource="other-owner/unrelated-repo",
        authorized_resources={"wamakologeorge-dev/amosclaude-clean"},
        capability="repository.read",
        allowed_capabilities={"repository.read"},
    )

    assert allowed is False
    assert "not authorized" in reason


def test_scope_blocks_denied_capability():
    allowed, reason = validate_scope(
        active_objective="investigate public framework error",
        requested_resource="wamakologeorge-dev/amosclaude-clean",
        authorized_resources={"wamakologeorge-dev/amosclaude-clean"},
        capability="research.account.create",
        allowed_capabilities={"research.public.search", "research.public.read"},
    )

    assert allowed is False
    assert reason == "capability is not allowed"


def test_hypotheses_are_ranked_by_evidence_and_confidence():
    weak = Hypothesis(statement="network issue", confidence=0.3)
    strong = Hypothesis(
        statement="dependency mismatch",
        supporting_evidence=("lock file version differs", "import error names removed symbol"),
        confidence=0.8,
    )

    ranked = rank_hypotheses((weak, strong))

    assert ranked[0] is strong


def test_verified_event_requires_evidence_reference():
    with pytest.raises(ValueError, match="require evidence"):
        OperationEvent(
            event_type="verification passed",
            objective="verify repair",
            resource="repository",
            capability="repository.tests.run",
            reason="confirm selected repair",
            status=OperationStatus.VERIFIED,
        )


def test_verified_response_requires_evidence():
    with pytest.raises(ValueError, match="require evidence"):
        ProfessionalResponse(
            objective="repair failing tests",
            status=OperationStatus.VERIFIED,
            verified_facts=("tests passed",),
            hypotheses=(),
            next_action="report result",
            next_action_reason="verification completed",
            evidence=(),
            confidence=1.0,
        )


def test_success_claim_requires_verified_status_and_evidence():
    evidence = Evidence(
        kind=EvidenceKind.TEST_RESULT,
        summary="focused tests passed",
        reference="pytest:12-passed",
    )

    assert can_claim_success(status=OperationStatus.ATTEMPTED, evidence=(evidence,)) is False
    assert can_claim_success(status=OperationStatus.VERIFIED, evidence=()) is False
    assert can_claim_success(status=OperationStatus.VERIFIED, evidence=(evidence,)) is True

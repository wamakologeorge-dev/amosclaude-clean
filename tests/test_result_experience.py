from amoscloud_ai.agent.result_experience import (
    EvidenceItem,
    ResultArtifact,
    ResultExperience,
    ResultKind,
    VerificationState,
    result_panel_message,
)


def test_mirror_update_explains_work_at_reading_speed():
    experience = ResultExperience(objective="Build a restaurant ordering platform")
    update = experience.add_update(
        phase="implementation",
        current_step="Creating the ordering API",
        reason="The interface needs a verified service for menu and order data.",
        changed_resources=("amoscloud_ai/api/routes/orders.py",),
        verification=("4 focused tests passed",),
        next_step="Connect the customer ordering screen.",
    )

    assert update.sequence == 1
    assert "pause" in update.user_controls
    assert "add idea" in update.user_controls
    assert "compare another path" in update.user_controls

    message = experience.latest_user_message()
    assert "Current objective" in message
    assert "What I am doing" in message
    assert "Why" in message
    assert "4 focused tests passed" in message
    assert "Connect the customer ordering screen" in message


def test_no_execution_result_means_no_success_claim():
    experience = ResultExperience(objective="Create a business website")

    message = experience.latest_user_message()

    assert "No execution result" in message
    assert "will not claim" in message


def test_verified_artifact_requires_evidence():
    without_evidence = ResultArtifact(
        artifact_id="site-1",
        title="Business website",
        kind=ResultKind.WEBSITE_PREVIEW,
        summary="Initial customer-facing website",
        preview_available=True,
        verification_state=VerificationState.VERIFIED,
    )
    with_evidence = ResultArtifact(
        artifact_id="site-2",
        title="Verified business website",
        kind=ResultKind.WEBSITE_PREVIEW,
        summary="Customer-facing website",
        location="https://example.invalid",
        preview_available=True,
        verification_state=VerificationState.VERIFIED,
        evidence=(
            EvidenceItem("test", "Browser checks", "Homepage and contact flow passed"),
            EvidenceItem("health", "Deployment health", "HTTP 200"),
        ),
    )

    assert without_evidence.can_claim_success is False
    assert with_evidence.can_claim_success is True
    assert "is verified" not in result_panel_message(without_evidence)
    assert "is verified" in result_panel_message(with_evidence)
    assert "Result panel" in result_panel_message(with_evidence)
    assert "Evidence panel" in result_panel_message(with_evidence)


def test_created_file_is_shown_as_real_downloadable_result():
    artifact = ResultArtifact(
        artifact_id="report-1",
        title="Project architecture report",
        kind=ResultKind.DOCUMENT,
        summary="Architecture, milestones, risks, and verification plan",
        location="/artifacts/project-architecture.pdf",
        preview_available=True,
        downloadable=True,
        verification_state=VerificationState.VERIFIED,
        evidence=(EvidenceItem("file", "Created file", "project-architecture.pdf"),),
    )

    message = result_panel_message(artifact)

    assert "open it in the Result panel" in message
    assert "download the created file" in message
    assert "is verified" in message


def test_failed_result_shows_failure_instead_of_pipeline_success():
    artifact = ResultArtifact(
        artifact_id="deploy-1",
        title="Production deployment",
        kind=ResultKind.DEPLOYMENT,
        summary="Deploy the approved application",
        verification_state=VerificationState.FAILED,
        evidence=(EvidenceItem("workflow", "Deployment check", "Health probe failed"),),
    )

    message = result_panel_message(artifact)

    assert "verification failed" in message
    assert "failure evidence" in message
    assert "verified" not in message.lower().split("verification failed")[0]


def test_new_programming_language_is_a_prototype_until_verified():
    artifact = ResultArtifact(
        artifact_id="language-1",
        title="Aster programming language prototype",
        kind=ResultKind.LANGUAGE_PROTOTYPE,
        summary="Grammar, parser, interpreter, examples, and tests",
        preview_available=True,
        downloadable=True,
        verification_state=VerificationState.RUNNING,
    )

    message = result_panel_message(artifact)

    assert "not verified yet" in message
    assert "work in progress" in message

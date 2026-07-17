"""Conversation-first result presentation for Amosclaud Autonomous.

The user should see real outcomes inside Amosclaud instead of receiving only a pipeline
link. This module defines result, evidence, and mirror-panel contracts. It does not
execute tools; callers must supply verified evidence from first-party operations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Iterable


class ResultKind(StrEnum):
    WEBSITE_PREVIEW = "website_preview"
    MOBILE_PREVIEW = "mobile_preview"
    IMAGE = "image"
    DOCUMENT = "document"
    SPREADSHEET = "spreadsheet"
    FILE = "file"
    CODE = "code"
    API_RESPONSE = "api_response"
    TEST_REPORT = "test_report"
    DEPLOYMENT = "deployment"
    LANGUAGE_PROTOTYPE = "language_prototype"


class VerificationState(StrEnum):
    PLANNED = "planned"
    RUNNING = "running"
    BLOCKED = "blocked"
    FAILED = "failed"
    VERIFIED = "verified"


@dataclass(frozen=True, slots=True)
class EvidenceItem:
    kind: str
    label: str
    value: str


@dataclass(frozen=True, slots=True)
class ResultArtifact:
    artifact_id: str
    title: str
    kind: ResultKind
    summary: str
    location: str | None = None
    preview_available: bool = False
    downloadable: bool = False
    verification_state: VerificationState = VerificationState.PLANNED
    evidence: tuple[EvidenceItem, ...] = ()

    @property
    def can_claim_success(self) -> bool:
        return self.verification_state == VerificationState.VERIFIED and bool(self.evidence)


@dataclass(frozen=True, slots=True)
class BuildUpdate:
    sequence: int
    objective: str
    phase: str
    current_step: str
    reason: str
    changed_resources: tuple[str, ...] = ()
    verification: tuple[str, ...] = ()
    next_step: str | None = None
    user_controls: tuple[str, ...] = (
        "pause",
        "stop",
        "ask",
        "add idea",
        "show plan",
        "compare another path",
    )


@dataclass(slots=True)
class ResultExperience:
    objective: str
    artifacts: list[ResultArtifact] = field(default_factory=list)
    updates: list[BuildUpdate] = field(default_factory=list)
    next_sequence: int = 1

    def add_update(
        self,
        *,
        phase: str,
        current_step: str,
        reason: str,
        changed_resources: Iterable[str] = (),
        verification: Iterable[str] = (),
        next_step: str | None = None,
    ) -> BuildUpdate:
        update = BuildUpdate(
            sequence=self.next_sequence,
            objective=self.objective,
            phase=phase,
            current_step=current_step,
            reason=reason,
            changed_resources=tuple(changed_resources),
            verification=tuple(verification),
            next_step=next_step,
        )
        self.next_sequence += 1
        self.updates.append(update)
        return update

    def add_artifact(self, artifact: ResultArtifact) -> None:
        self.artifacts.append(artifact)

    def latest_user_message(self) -> str:
        """Render a readable progress message suitable for chat and the mirror panel."""
        if not self.updates:
            return (
                f"We are preparing the plan for: {self.objective}. No execution result has been "
                "recorded yet, so I will not claim that anything was built."
            )
        update = self.updates[-1]
        changed = ", ".join(update.changed_resources) or "No file change recorded"
        verified = ", ".join(update.verification) or "Verification is still pending"
        next_step = update.next_step or "I will keep the conversation aligned with the approved plan."
        return (
            f"Current objective: {update.objective}\n"
            f"Current phase: {update.phase}\n"
            f"What I am doing: {update.current_step}\n"
            f"Why: {update.reason}\n"
            f"Changed or produced: {changed}\n"
            f"Verification: {verified}\n"
            f"Next: {next_step}"
        )


def result_panel_message(artifact: ResultArtifact) -> str:
    """Describe what the user can inspect without overstating execution success."""
    visibility = []
    if artifact.preview_available:
        visibility.append("open it in the Result panel")
    if artifact.downloadable:
        visibility.append("download the created file")
    available = " and ".join(visibility) or "review its recorded details"

    if artifact.can_claim_success:
        return (
            f"{artifact.title} is verified. You can {available}. The Evidence panel shows the "
            "files, checks, and operation records supporting this result."
        )
    if artifact.verification_state == VerificationState.FAILED:
        return (
            f"{artifact.title} was produced but verification failed. You can {available}, and I "
            "will show the failure evidence before proposing the next repair."
        )
    if artifact.verification_state == VerificationState.BLOCKED:
        return (
            f"{artifact.title} is blocked. No success claim will be made. You can {available} and "
            "review the blocker in the Evidence panel."
        )
    return (
        f"{artifact.title} is not verified yet. You can {available}, but I will describe it as a "
        "work in progress until first-party evidence confirms the result."
    )

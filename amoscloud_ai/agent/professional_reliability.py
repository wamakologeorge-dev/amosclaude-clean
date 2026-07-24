"""Evidence-first reliability primitives for Amosclaud Autonomous.

This module provides deterministic contracts for facts, hypotheses, operation events,
source ranking, scope checks, and sanitization. It deliberately does not perform web
research or claim that an external action happened; callers must attach real evidence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import IntEnum, StrEnum
from typing import Iterable


class EvidenceKind(StrEnum):
    COMMAND_OUTPUT = "command_output"
    TEST_RESULT = "test_result"
    FILE_CONTENT = "file_content"
    COMMIT = "commit"
    DEPLOYMENT = "deployment"
    PUBLIC_SOURCE = "public_source"
    USER_AUTHORIZATION = "user_authorization"


class OperationStatus(StrEnum):
    PLANNED = "planned"
    ATTEMPTED = "attempted"
    BLOCKED = "blocked"
    FAILED = "failed"
    VERIFIED = "verified"


class SourceTier(IntEnum):
    OFFICIAL_DOCUMENTATION = 1
    MAINTAINER_SOURCE = 2
    FRAMEWORK_DOCUMENTATION = 3
    PUBLIC_ISSUE_TRACKER = 4
    STACK_OVERFLOW = 5
    TECHNICAL_ARTICLE = 6
    AI_GENERATED = 7


@dataclass(frozen=True, slots=True)
class Evidence:
    kind: EvidenceKind
    summary: str
    reference: str
    observed_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


@dataclass(frozen=True, slots=True)
class Hypothesis:
    statement: str
    supporting_evidence: tuple[str, ...] = ()
    contradicting_evidence: tuple[str, ...] = ()
    confidence: float = 0.0

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")


@dataclass(frozen=True, slots=True)
class OperationEvent:
    event_type: str
    objective: str
    resource: str
    capability: str
    reason: str
    status: OperationStatus
    evidence_references: tuple[str, ...] = ()
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def __post_init__(self) -> None:
        if self.status is OperationStatus.VERIFIED and not self.evidence_references:
            raise ValueError("verified events require evidence references")


@dataclass(frozen=True, slots=True)
class ProfessionalResponse:
    objective: str
    status: OperationStatus
    verified_facts: tuple[str, ...]
    hypotheses: tuple[Hypothesis, ...]
    next_action: str
    next_action_reason: str
    evidence: tuple[Evidence, ...]
    confidence: float
    blockers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")
        if self.status is OperationStatus.VERIFIED and not self.evidence:
            raise ValueError("verified responses require evidence")


_SECRET_PATTERNS = (
    re.compile(r"(?i)(api[_-]?key|token|password|secret)\s*[:=]\s*[^\s,;]+"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"(?i)authorization:\s*bearer\s+[^\s]+"),
)


def sanitize_for_public_research(text: str) -> tuple[str, tuple[str, ...]]:
    """Remove common secrets and return the sanitized text plus redaction reasons."""

    sanitized = text or ""
    redactions: list[str] = []
    for pattern in _SECRET_PATTERNS:
        sanitized, count = pattern.subn("[REDACTED]", sanitized)
        if count:
            redactions.append(f"redacted {count} sensitive value(s)")
    return sanitized, tuple(redactions)


def validate_scope(
    *,
    active_objective: str,
    requested_resource: str,
    authorized_resources: Iterable[str],
    capability: str,
    allowed_capabilities: Iterable[str],
) -> tuple[bool, str]:
    """Check that an operation is tied to an objective, resource, and capability."""

    if not active_objective.strip():
        return False, "missing active objective"
    if requested_resource not in set(authorized_resources):
        return False, "resource is not authorized for the active objective"
    if capability not in set(allowed_capabilities):
        return False, "capability is not allowed"
    return True, "scope validated"


def rank_hypotheses(hypotheses: Iterable[Hypothesis]) -> tuple[Hypothesis, ...]:
    """Rank by calibrated confidence and evidence balance, highest first."""

    def score(item: Hypothesis) -> tuple[float, int, int]:
        return (
            item.confidence,
            len(item.supporting_evidence),
            -len(item.contradicting_evidence),
        )

    return tuple(sorted(hypotheses, key=score, reverse=True))


def can_claim_success(*, status: OperationStatus, evidence: Iterable[Evidence]) -> bool:
    """Success may be claimed only for verified status with concrete evidence."""

    return status is OperationStatus.VERIFIED and any(True for _ in evidence)

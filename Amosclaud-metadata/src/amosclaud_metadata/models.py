"""Typed records for the Amosclaud-metadata canonical history."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
import uuid


def utc_now() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


class VerificationState(str, Enum):
    """Lifecycle state of a metadata record's truthfulness claim.

    - ``OBSERVED`` — the event was seen but not independently confirmed.
    - ``VERIFIED`` — at least one evidence reference confirms the claim.
    - ``FAILED`` — the operation completed with a failure outcome.
    - ``SUPERSEDED`` — a newer record replaces this one; kept for audit purposes.
    """

    OBSERVED = "observed"
    VERIFIED = "verified"
    FAILED = "failed"
    SUPERSEDED = "superseded"


@dataclass(frozen=True)
class MetadataEnvelope:
    """Immutable wrapper that carries one metadata record to persistent storage.

    Every record written by :class:`~amosclaud_metadata.service.AmosclaudMetadataService`
    is wrapped in this envelope before being handed to
    :class:`~amosclaud_metadata.storage.JsonMetadataStore`.

    Attributes:
        record_type: Category name used as the storage sub-directory
            (e.g. ``"commit"``, ``"deployment"``).
        payload: The actual record data as a plain dict.
        source: Originating system or agent identifier.
        schema_version: Envelope schema version for forward compatibility.
        record_id: UUID assigned at creation; used as the file name.
        created_at: ISO 8601 UTC timestamp set at creation.
        verification: Truthfulness claim for this record.
        evidence: Ordered tuple of opaque references (commit SHAs, URLs, etc.)
            that support the ``verification`` claim.
    """

    record_type: str
    payload: dict[str, Any]
    source: str = "amosclaud-autonomous"
    schema_version: str = "1.0"
    record_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: str = field(default_factory=utc_now)
    verification: VerificationState = VerificationState.OBSERVED
    evidence: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-safe dict, converting ``verification`` to its string value."""
        data = asdict(self)
        data["verification"] = self.verification.value
        return data


@dataclass(frozen=True)
class RepositoryRecord:
    """Snapshot of a Git repository's identity at a point in time.

    Attributes:
        full_name: ``owner/repo`` path as parsed from the remote URL.
        default_branch: Branch name of the upstream default (e.g. ``"main"``).
        workspace: Absolute local path to the repository root.
        remote_url: ``origin`` remote URL, or ``""`` when not configured.
        commit_sha: HEAD commit SHA at the time of the snapshot.
    """

    full_name: str
    default_branch: str
    workspace: str
    remote_url: str = ""
    commit_sha: str = ""


@dataclass(frozen=True)
class CommitRecord:
    """Evidence record for a single Git commit produced by the agent.

    Attributes:
        repository: ``owner/repo`` identifier matching :attr:`RepositoryRecord.full_name`.
        sha: Full commit SHA.
        branch: Branch the commit was made on.
        objective: The agent objective that caused this commit.
        summary: Human-readable description of the change.
        files_changed: Paths of files touched by this commit.
        tests: Test identifiers executed to verify the change.
        parent_shas: SHA(s) of the parent commit(s).
        author: Identity string of the commit author.
    """

    repository: str
    sha: str
    branch: str
    objective: str
    summary: str
    files_changed: tuple[str, ...] = ()
    tests: tuple[str, ...] = ()
    parent_shas: tuple[str, ...] = ()
    author: str = "amosclaud-autonomous"


@dataclass(frozen=True)
class MissionRecord:
    """Progress snapshot of a multi-step agent mission.

    Attributes:
        mission_id: Unique mission identifier.
        objective: Original plain-language goal.
        mode: Execution mode (e.g. ``"build"``, ``"autonomous-check"``).
        status: Current terminal or in-progress status string.
        current_phase: Name of the phase the mission is in.
        completed_steps: Step names that have finished successfully.
        remaining_steps: Step names that have not yet started.
        result_locations: Paths or URLs where mission outputs can be found.
    """

    mission_id: str
    objective: str
    mode: str
    status: str
    current_phase: str
    completed_steps: tuple[str, ...] = ()
    remaining_steps: tuple[str, ...] = ()
    result_locations: tuple[str, ...] = ()


@dataclass(frozen=True)
class PipelineRecord:
    """CI/CD pipeline execution summary.

    Attributes:
        pipeline_id: Unique pipeline identifier.
        mission_id: Mission that triggered this pipeline.
        status: Terminal or in-progress status string.
        checks_passed: Number of checks that completed successfully.
        checks_failed: Number of checks that failed.
        checks_warning: Number of checks that produced warnings.
        runtime_seconds: Wall-clock execution time.
    """

    pipeline_id: str
    mission_id: str
    status: str
    checks_passed: int = 0
    checks_failed: int = 0
    checks_warning: int = 0
    runtime_seconds: float = 0.0


@dataclass(frozen=True)
class DeploymentRecord:
    """Evidence record for a deployment performed by the agent.

    Attributes:
        deployment_id: Unique deployment identifier.
        environment: Target environment name (e.g. ``"staging"``, ``"production"``).
        provider: Infrastructure provider (e.g. ``"heroku"``, ``"aws"``).
        status: Terminal deployment status.
        commit_sha: The commit that was deployed.
        health_url: URL used to verify the deployment is healthy; ``""`` if unused.
        rollback_target: Deployment ID to roll back to on failure; ``""`` if not set.
    """

    deployment_id: str
    environment: str
    provider: str
    status: str
    commit_sha: str
    health_url: str = ""
    rollback_target: str = ""


@dataclass(frozen=True)
class RepairRecord:
    """Audit trail for an automated bug or incident repair.

    Attributes:
        issue_id: External issue tracker identifier.
        title: Short issue title.
        root_cause: Plain-language description of the identified cause.
        treatment: Description of the fix applied.
        status: Current repair status (e.g. ``"resolved"``, ``"failed"``).
        attempts: Number of repair attempts made.
        changed_files: Files modified during the repair.
        verification: Evidence references confirming the fix.
    """

    issue_id: str
    title: str
    root_cause: str
    treatment: str
    status: str
    attempts: int = 0
    changed_files: tuple[str, ...] = ()
    verification: tuple[str, ...] = ()


@dataclass(frozen=True)
class HealthRecord:
    """Point-in-time health observation for a single system component.

    Attributes:
        component: Component name or identifier.
        status: Health status string (e.g. ``"healthy"``, ``"degraded"``).
        latency_ms: Observed response latency in milliseconds; ``None`` if not measured.
        detail: Optional freeform annotation.
        last_heartbeat: ISO 8601 UTC timestamp of the observation.
    """

    component: str
    status: str
    latency_ms: float | None = None
    detail: str = ""
    last_heartbeat: str = field(default_factory=utc_now)

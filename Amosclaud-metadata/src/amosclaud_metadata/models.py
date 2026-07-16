"""Typed records for the Amosclaud-metadata canonical history."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
import uuid


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class VerificationState(str, Enum):
    OBSERVED = "observed"
    VERIFIED = "verified"
    FAILED = "failed"
    SUPERSEDED = "superseded"


@dataclass(frozen=True)
class MetadataEnvelope:
    record_type: str
    payload: dict[str, Any]
    source: str = "amosclaud-autonomous"
    schema_version: str = "1.0"
    record_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: str = field(default_factory=utc_now)
    verification: VerificationState = VerificationState.OBSERVED
    evidence: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["verification"] = self.verification.value
        return data


@dataclass(frozen=True)
class RepositoryRecord:
    full_name: str
    default_branch: str
    workspace: str
    remote_url: str = ""
    commit_sha: str = ""


@dataclass(frozen=True)
class CommitRecord:
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
    pipeline_id: str
    mission_id: str
    status: str
    checks_passed: int = 0
    checks_failed: int = 0
    checks_warning: int = 0
    runtime_seconds: float = 0.0


@dataclass(frozen=True)
class DeploymentRecord:
    deployment_id: str
    environment: str
    provider: str
    status: str
    commit_sha: str
    health_url: str = ""
    rollback_target: str = ""


@dataclass(frozen=True)
class RepairRecord:
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
    component: str
    status: str
    latency_ms: float | None = None
    detail: str = ""
    last_heartbeat: str = field(default_factory=utc_now)

"""Verification evidence exchanged by Agent, Fixer, repository, and CI."""

from __future__ import annotations

from dataclasses import dataclass, field

from .statuses import ExecutionStatus


@dataclass(slots=True)
class VerificationEvidence:
    verification_id: str
    status: ExecutionStatus
    commit_sha: str | None = None
    repository_id: str | int | None = None
    pull_request_id: str | int | None = None
    changed_files: list[str] = field(default_factory=list)
    checks: list[str] = field(default_factory=list)
    artifact_urls: list[str] = field(default_factory=list)
    failure_reason: str | None = None

    def assert_success_claim_allowed(self) -> None:
        if self.status is not ExecutionStatus.PASSED:
            raise ValueError("Success cannot be claimed before verification passes")
        if not self.verification_id.strip():
            raise ValueError("A verification_id is required")
        if not self.commit_sha:
            raise ValueError("A verified commit SHA is required")
        if not self.checks:
            raise ValueError("At least one completed verification check is required")

    def as_dict(self) -> dict[str, object]:
        return {
            "verification_id": self.verification_id,
            "status": self.status.value,
            "commit_sha": self.commit_sha,
            "repository_id": self.repository_id,
            "pull_request_id": self.pull_request_id,
            "changed_files": list(self.changed_files),
            "checks": list(self.checks),
            "artifact_urls": list(self.artifact_urls),
            "failure_reason": self.failure_reason,
        }

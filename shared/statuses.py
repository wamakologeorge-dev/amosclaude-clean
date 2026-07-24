"""One status vocabulary for Agent, Fixer, CI, repository, and deployment."""

from enum import Enum


class ExecutionStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    VERIFYING = "verifying"
    PASSED = "passed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    NEEDS_REVIEW = "needs_review"
    ROLLED_BACK = "rolled_back"

    @property
    def terminal(self) -> bool:
        return self in {
            self.PASSED,
            self.FAILED,
            self.CANCELLED,
            self.NEEDS_REVIEW,
            self.ROLLED_BACK,
        }

    @property
    def successful(self) -> bool:
        return self is self.PASSED

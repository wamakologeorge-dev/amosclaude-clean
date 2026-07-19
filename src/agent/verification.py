"""Evidence-based completion checks for the ReAct loop."""
from __future__ import annotations

from dataclasses import dataclass

from .observations import Observation


@dataclass(frozen=True)
class VerificationResult:
    passed: bool
    summary: str


class CompletionVerifier:
    """Require successful evidence before an execution task may claim success."""

    def verify(
        self,
        observations: list[Observation],
        *,
        execution_required: bool,
    ) -> VerificationResult:
        if not execution_required:
            return VerificationResult(True, "guidance task requires no tool execution")
        if not observations:
            return VerificationResult(False, "no action evidence was produced")
        failures = [item for item in observations if not item.success]
        if failures:
            return VerificationResult(
                False,
                f"{len(failures)} action observation(s) failed",
            )
        return VerificationResult(True, "all action observations succeeded")

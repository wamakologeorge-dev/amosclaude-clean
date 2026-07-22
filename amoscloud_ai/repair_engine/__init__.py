"""Amosclaud autonomous decision and self-healing repair engine."""

from .core import (
    AutonomousRepairEngine,
    Doctor,
    Evidence,
    Finding,
    Fixer,
    Repair,
    RepairMemory,
    RepairReport,
    Severity,
    Verdict,
    Verifier,
)
from .asset_checks import safer_local_assets
from .decision_engine import AutonomousDecisionEngine, RepairDecision
from .json_repairs import json_aware_fixer_apply, safer_json_syntax

# Root-relative links are application URLs, not host filesystem paths. Keep the
# core class API stable while replacing the overly broad legacy asset check.
Doctor._local_assets = safer_local_assets  # type: ignore[method-assign]

# JSON-with-comments is common in developer tooling such as CodeSandbox. It is
# repairable only when comments/trailing commas can be removed without touching
# quoted strings and the normalized result parses successfully.
Doctor._json_syntax = safer_json_syntax  # type: ignore[method-assign]
_core_fixer_apply = Fixer.apply


def _verified_fixer_apply(self: Fixer, findings: list[Finding]) -> list[Repair]:
    return json_aware_fixer_apply(_core_fixer_apply, self, findings)


Fixer.apply = _verified_fixer_apply  # type: ignore[method-assign]

__all__ = [
    "AutonomousDecisionEngine",
    "AutonomousRepairEngine",
    "Doctor",
    "Evidence",
    "Finding",
    "Fixer",
    "Repair",
    "RepairDecision",
    "RepairMemory",
    "RepairReport",
    "Severity",
    "Verdict",
    "Verifier",
]

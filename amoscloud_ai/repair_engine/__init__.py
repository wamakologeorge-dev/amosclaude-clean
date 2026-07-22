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

# Root-relative links are application URLs, not host filesystem paths. Keep the
# core class API stable while replacing the overly broad legacy asset check.
Doctor._local_assets = safer_local_assets  # type: ignore[method-assign]

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

"""Amosclaud autonomous decision and self-healing repair engine."""

import os
from collections.abc import Sequence
from pathlib import Path

from amoscloud_ai.repair_knowledge import VerifiedRepairMemory

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
from .healing import HealingRecommendation, doctor_healing_run, recommendations
from .json_repairs import json_aware_fixer_apply, safer_json_syntax

Doctor._local_assets = safer_local_assets  # type: ignore[method-assign]
Doctor._json_syntax = safer_json_syntax  # type: ignore[method-assign]
_core_basic_text_checks = Doctor._basic_text_checks
_core_fixer_apply = Fixer.apply
_core_decide = AutonomousDecisionEngine.decide
_core_run = AutonomousDecisionEngine.run
_core_autonomous_run = AutonomousRepairEngine.run


def _has_conflict_block(lines: list[str], separator_index: int) -> bool:
    """Return true only when an equals separator belongs to a full conflict block."""
    has_opener = any(
        line.strip() == "<<<<<<<" or line.strip().startswith("<<<<<<< ")
        for line in lines[:separator_index]
    )
    has_closer = any(
        line.strip() == ">>>>>>>" or line.strip().startswith(">>>>>>> ")
        for line in lines[separator_index + 1 :]
    )
    return has_opener and has_closer


def _precise_basic_text_checks(self: Doctor, path: Path) -> list[Finding]:
    """Ignore decorative separators while preserving real conflict markers."""
    findings = _core_basic_text_checks(self, path)
    if not any(item.code == "merge-conflict" for item in findings):
        return findings
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return findings
    verified: list[Finding] = []
    for finding in findings:
        if finding.code != "merge-conflict" or not finding.line:
            verified.append(finding)
            continue
        index = finding.line - 1
        if index < 0 or index >= len(lines):
            verified.append(finding)
            continue
        marker = lines[index].strip()
        is_opener = marker == "<<<<<<<" or marker.startswith("<<<<<<< ")
        is_closer = marker == ">>>>>>>" or marker.startswith(">>>>>>> ")
        is_separator = marker == "=======" and _has_conflict_block(lines, index)
        if is_opener or is_closer or is_separator:
            verified.append(finding)
    return verified


def _verified_fixer_apply(self: Fixer, findings: Sequence[Finding]) -> list[Repair]:
    return json_aware_fixer_apply(_core_fixer_apply, self, findings)


def _verified_decide(
    self: AutonomousDecisionEngine,
    findings: Sequence[Finding],
) -> RepairDecision | None:
    """Prioritize a deterministic JSON normalization over cosmetic repairs."""
    if not self.target_paths:
        candidates = sorted(
            (
                item
                for item in findings
                if item.code == "json-syntax" and item.severity == Severity.REPAIRABLE and item.path
            ),
            key=lambda item: (item.path or "", item.line or 0),
        )
        if candidates:
            selected = candidates[0]
            return RepairDecision(
                paths=(selected.path,),
                finding_codes=("json-syntax",),
                confidence=96,
                risk="low",
                reason=(
                    "Doctor proved that removing comments/trailing commas yields valid JSON; "
                    "the repair is prioritized over unrelated cosmetic findings."
                ),
            )
    return _core_decide(self, findings)


def _doctor_led_run(self: AutonomousDecisionEngine, apply: bool = False) -> RepairReport:
    return doctor_healing_run(_core_run, self, apply=apply)


def _finding_query(findings: Sequence[Finding]) -> str:
    return "\n".join(f"{item.code} {item.message} {item.path or ''}" for item in findings)


def _memory_guided_decide(
    self: AutonomousDecisionEngine,
    findings: Sequence[Finding],
) -> RepairDecision | None:
    """Prefer a previously verified technique without executing stored code."""
    try:
        memory = VerifiedRepairMemory.for_repository(self.root)
        paths = [item.path for item in findings if item.path]
        matches = memory.recall(_finding_query(findings), changed_files=paths)
    except (OSError, ValueError):
        matches = []
    if matches:
        known = {signal.replace("_", "-").replace(" ", "-") for signal in matches[0].signals}
        selected = [
            item
            for item in findings
            if item.severity == Severity.REPAIRABLE
            and item.path
            and item.code.replace("_", "-") in known
        ]
        if selected:
            selected_paths = tuple(sorted({item.path for item in selected if item.path}))
            return RepairDecision(
                paths=selected_paths,
                finding_codes=tuple(sorted({item.code for item in selected})),
                confidence=99,
                risk="low",
                reason=(
                    "Amosclaud Storage Memory matched verified technique "
                    f"{matches[0].technique_id}; Fixer will still use only trusted "
                    "deterministic handlers and Doctor will re-verify the current files."
                ),
            )
    return _verified_decide(self, findings)


def _memory_evidence(memory: VerifiedRepairMemory, findings: Sequence[Finding]) -> Evidence:
    try:
        paths = [item.path for item in findings if item.path]
        matches = memory.recall(_finding_query(findings), changed_files=paths)
    except (OSError, ValueError) as exc:
        return Evidence(
            "Amosclaud Storage Memory recall",
            True,
            output=f"Memory unavailable; no stored technique was executed: {type(exc).__name__}",
        )
    if not matches:
        return Evidence(
            "Amosclaud Storage Memory recall",
            True,
            output="No verified technique matched; normal bounded diagnosis continued.",
        )
    ids = ", ".join(item.technique_id for item in matches)
    return Evidence(
        "Amosclaud Storage Memory recall",
        True,
        output=f"Matched declarative verified technique(s): {ids}. No old patch was executed.",
    )


def _record_capability(
    memory: VerifiedRepairMemory,
    report: RepairReport,
    *,
    apply: bool,
) -> Evidence:
    if not apply:
        return Evidence(
            "Amosclaud capability level",
            True,
            output="Diagnosis-only run; no learning or level change was attempted.",
        )
    try:
        if report.final_verdict == Verdict.PASS and report.changed_files:
            result = memory.record_report(
                report,
                source_run_id=os.getenv("GITHUB_RUN_ID", ""),
            )
            state = "new technique" if result.get("novel") else "known technique reused"
            return Evidence(
                "Amosclaud capability level",
                True,
                output=(
                    f"{state}; level={result.get('level', 1)}/{result.get('max_level', 5)}; "
                    f"technique={result.get('technique_id', 'none')}"
                ),
            )
        if report.final_verdict != Verdict.PASS:
            status = memory.record_failure("repair verification failed")
            return Evidence(
                "Amosclaud capability level",
                True,
                output=(
                    "Repair failed verification; no level awarded; "
                    f"level={status.get('level', 1)}/{status.get('max_level', 5)}"
                ),
            )
        status = memory.status()
        return Evidence(
            "Amosclaud capability level",
            True,
            output=(
                "No repository change was required; no level awarded; "
                f"level={status.get('level', 1)}/{status.get('max_level', 5)}"
            ),
        )
    except (OSError, ValueError) as exc:
        return Evidence(
            "Amosclaud capability level",
            True,
            output=f"Verified repair completed but memory was not updated: {type(exc).__name__}",
        )


def _memory_aware_decision_run(
    self: AutonomousDecisionEngine,
    apply: bool = False,
) -> RepairReport:
    initial = self.diagnose()
    memory = VerifiedRepairMemory.for_repository(self.root)
    recall = _memory_evidence(memory, initial)
    report = _doctor_led_run(self, apply=apply)
    report.evidence.append(recall)
    report.evidence.append(_record_capability(memory, report, apply=apply))
    return report


def _memory_aware_autonomous_run(
    self: AutonomousRepairEngine,
    apply: bool = False,
) -> RepairReport:
    initial = self.doctor.diagnose()
    memory = VerifiedRepairMemory.for_repository(self.root)
    recall = _memory_evidence(memory, initial)
    report = _core_autonomous_run(self, apply=apply)
    report.evidence.append(recall)
    report.evidence.append(_record_capability(memory, report, apply=apply))
    return report


Doctor._basic_text_checks = _precise_basic_text_checks  # type: ignore[method-assign]
Fixer.apply = _verified_fixer_apply  # type: ignore[method-assign]
AutonomousDecisionEngine.decide = _memory_guided_decide  # type: ignore[method-assign]
AutonomousDecisionEngine.run = _memory_aware_decision_run  # type: ignore[method-assign]
AutonomousRepairEngine.run = _memory_aware_autonomous_run  # type: ignore[method-assign]

__all__ = [
    "AutonomousDecisionEngine",
    "AutonomousRepairEngine",
    "Doctor",
    "Evidence",
    "Finding",
    "Fixer",
    "HealingRecommendation",
    "Repair",
    "RepairDecision",
    "RepairMemory",
    "RepairReport",
    "Severity",
    "Verdict",
    "VerifiedRepairMemory",
    "Verifier",
    "recommendations",
]

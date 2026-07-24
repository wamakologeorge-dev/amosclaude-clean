from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .core import (
    Doctor,
    Evidence,
    Finding,
    Fixer,
    RepairMemory,
    RepairReport,
    Severity,
    Verdict,
    Verifier,
    relative,
    utc_now,
)


@dataclass(frozen=True, slots=True)
class RepairDecision:
    """Evidence-backed decision for one repair attempt."""

    paths: tuple[str, ...]
    finding_codes: tuple[str, ...]
    confidence: int
    risk: str
    reason: str


class AutonomousDecisionEngine:
    """Objective-aware deterministic repair loop with focused verification.

    Doctor verifies the exact requested repair scope. Unrelated repository
    findings are recorded as deferred evidence and do not block a safe,
    explicitly scoped repair. Fixer remains the only component that edits code.
    """

    def __init__(
        self,
        root: Path,
        *,
        objective: str = "",
        required_files: Sequence[str] = (),
        commands: Sequence[Sequence[str]] = (),
        max_attempts: int = 3,
        memory_path: Path | None = None,
    ) -> None:
        self.root = root.resolve()
        self.objective = objective.strip()
        self.doctor = Doctor(self.root, required_files)
        self.fixer = Fixer(self.root)
        self.verifier = Verifier(self.root)
        self.commands = list(commands)
        self.max_attempts = max(1, max_attempts)
        self.memory = RepairMemory(memory_path or self.root / ".amosclaud" / "repair-memory.jsonl")
        self.target_paths = self._extract_target_paths(self.objective)
        self.deferred_findings: list[Finding] = []

    def _extract_target_paths(self, objective: str) -> tuple[str, ...]:
        candidates: list[str] = []
        candidates.extend(value.strip() for value in re.findall(r"`([^`]+)`", objective))
        candidates.extend(
            value.strip()
            for value in re.findall(r"(?<![\w.-])([\w./-]+\.[A-Za-z0-9]{1,12})(?![\w.-])", objective)
        )

        resolved: list[str] = []
        for candidate in candidates:
            candidate = candidate.removeprefix("./")
            path = (self.root / candidate).resolve()
            try:
                path.relative_to(self.root)
            except ValueError:
                continue
            if path.is_file():
                rel = relative(path, self.root)
                if rel not in resolved:
                    resolved.append(rel)
        return tuple(resolved)

    def _focused_findings(self) -> list[Finding]:
        """Inspect explicit objective files, including normally ignored suffixes."""
        findings: list[Finding] = []
        for rel in self.target_paths:
            path = self.root / rel
            if not path.is_file():
                findings.append(
                    Finding("missing-objective-file", "Objective file does not exist", Severity.CRITICAL, rel)
                )
                continue
            findings.extend(self.doctor._basic_text_checks(path))
            if path.suffix == ".py":
                findings.extend(self.doctor._python_syntax(path))
            elif path.suffix == ".json":
                findings.extend(self.doctor._json_syntax(path))
            elif path.suffix == ".sh":
                findings.extend(self.doctor._shell_syntax(path))
            elif path.suffix in {".yml", ".yaml"}:
                findings.extend(self.doctor._workflow_checks(path))
        return findings

    def diagnose(self) -> list[Finding]:
        global_findings = self.doctor.diagnose()
        if not self.target_paths:
            self.deferred_findings = []
            return global_findings

        focused = self._focused_findings()
        focused_keys = {(item.code, item.path, item.line) for item in focused}
        self.deferred_findings = [
            item
            for item in global_findings
            if (item.code, item.path, item.line) not in focused_keys
            and item.path not in self.target_paths
        ]
        return focused

    def decide(self, findings: Sequence[Finding]) -> RepairDecision | None:
        repairable = [item for item in findings if item.severity == Severity.REPAIRABLE and item.path]
        if not repairable:
            return None

        priority = {
            "merge-conflict": 100,
            "unpinned-action": 80,
            "yaml-tabs": 70,
            "trailing-whitespace": 50,
            "missing-final-newline": 40,
        }

        def score(item: Finding) -> tuple[int, int, str, int]:
            explicit = 1 if item.path in self.target_paths else 0
            return (explicit, priority.get(item.code, 10), item.path or "", -(item.line or 0))

        ranked = sorted(repairable, key=score, reverse=True)
        if self.target_paths:
            selected_paths = tuple(path for path in self.target_paths if any(item.path == path for item in ranked))
        else:
            selected_paths = (ranked[0].path,) if ranked[0].path else ()
        selected = [item for item in ranked if item.path in selected_paths]
        if not selected:
            return None

        confidence = 98 if self.target_paths else 82
        codes = tuple(sorted({item.code for item in selected}))
        reason = (
            "The objective explicitly names the selected file(s); Doctor and Fixer are scoped to those files."
            if self.target_paths
            else "No file was named; the highest-priority low-risk deterministic finding was selected."
        )
        return RepairDecision(selected_paths, codes, confidence, "low", reason)

    def _snapshot(self, paths: Sequence[str]) -> dict[str, bytes]:
        return {rel: (self.root / rel).read_bytes() for rel in paths if (self.root / rel).is_file()}

    def _restore(self, snapshot: dict[str, bytes]) -> None:
        for rel, content in snapshot.items():
            (self.root / rel).write_bytes(content)

    def _verification(self, findings: Sequence[Finding]) -> list[Evidence]:
        static_verdict = self.doctor.classify(findings)
        evidence = [
            Evidence(
                "Amosclaud Doctor scoped static verification",
                static_verdict == Verdict.HEALTHY,
                output=static_verdict.value,
            )
        ]
        if self.target_paths and self.deferred_findings:
            summary = "; ".join(
                f"{item.code}:{item.path or 'repository'}" for item in self.deferred_findings[:20]
            )
            evidence.append(
                Evidence(
                    "Unrelated repository findings deferred",
                    True,
                    output=summary,
                )
            )
        if static_verdict == Verdict.HEALTHY and self.commands:
            evidence.extend(self.verifier.run(self.commands))
        return evidence

    def run(self, apply: bool = False) -> RepairReport:
        report = RepairReport(root=str(self.root), started_at=utc_now())
        initial = self.diagnose()
        report.findings = initial
        report.diagnosis = self.doctor.classify(initial)

        if not apply:
            report.evidence = self._verification(initial)
        else:
            previous_signature: tuple[tuple[str, str | None, int | None], ...] | None = None
            for attempt in range(1, self.max_attempts + 1):
                report.attempts = attempt
                decision = self.decide(report.findings)
                if decision is None:
                    break

                signature = tuple(sorted((item.code, item.path, item.line) for item in report.findings))
                if signature == previous_signature:
                    report.evidence.append(
                        Evidence("Self-healing progress guard", False, output="No new diagnosis after retry")
                    )
                    break
                previous_signature = signature

                report.evidence.append(
                    Evidence(
                        f"Decision attempt {attempt}: {', '.join(decision.paths)}",
                        True,
                        output=(
                            f"confidence={decision.confidence}% risk={decision.risk}; "
                            f"findings={','.join(decision.finding_codes)}; {decision.reason}"
                        ),
                    )
                )

                selected = [
                    item
                    for item in report.findings
                    if item.severity == Severity.REPAIRABLE and item.path in decision.paths
                ]
                snapshot = self._snapshot(decision.paths)
                repairs = self.fixer.apply(selected)
                changed = [item.path for item in repairs if item.changed]
                report.repairs.extend(repairs)

                if not changed:
                    report.evidence.append(
                        Evidence("Repair attempt produced a repository change", False, output="No files changed")
                    )
                    break

                after = self.diagnose()
                attempt_evidence = self._verification(after)
                report.evidence.extend(attempt_evidence)
                if all(item.passed for item in attempt_evidence):
                    report.findings = after
                    report.changed_files = sorted(set(changed))
                    break

                self._restore(snapshot)
                report.evidence.append(
                    Evidence("Rollback unverified repair", True, output=", ".join(changed))
                )
                report.findings = self.diagnose()

        if not report.evidence:
            report.evidence = self._verification(report.findings)

        report.final_verdict = (
            Verdict.PASS if report.evidence and all(item.passed for item in report.evidence) else Verdict.FAIL
        )
        if report.final_verdict != Verdict.PASS:
            report.changed_files = []

        report.finished_at = utc_now()
        self.memory.record(report)
        return report


def objective_from_environment() -> str:
    """Read the trusted workflow objective without requiring workflow rewrites."""
    return os.environ.get("OBJECTIVE", "").strip()

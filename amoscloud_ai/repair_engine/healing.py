"""Bounded Doctor-led healing for Amosclaud Autonomous.

Doctor remains the verification authority, but a non-healthy diagnosis no longer
ends the run after the first safe edit. The coordinator accumulates distinct
low-risk repairs, re-diagnoses after every cycle, and verifies only after the
selected safe strategies have had a chance to heal the complete repair scope.
All accumulated changes are rolled back if the final verification does not pass.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass

from .core import Evidence, Finding, RepairReport, Severity, Verdict, utc_now


@dataclass(frozen=True, slots=True)
class HealingRecommendation:
    finding_code: str
    path: str | None
    next_strategy: str
    confidence: int
    human_required: bool
    reason: str


_STRATEGIES: dict[str, tuple[str, int, bool, str]] = {
    "json-syntax": (
        "verified-json-normalizer",
        96,
        False,
        "Normalize comments or trailing commas only when the result parses as strict JSON.",
    ),
    "trailing-whitespace": (
        "safe-static-repair",
        99,
        False,
        "Trim whitespace without changing program semantics.",
    ),
    "missing-final-newline": (
        "safe-static-repair",
        99,
        False,
        "Add the required final newline.",
    ),
    "yaml-tabs": (
        "safe-workflow-normalizer",
        97,
        False,
        "Replace indentation tabs and re-parse the workflow.",
    ),
    "unpinned-action": (
        "known-action-pin-repair",
        95,
        False,
        "Use the allowlisted immutable action commit when one is known.",
    ),
    "python-syntax": (
        "semantic-code-repair",
        0,
        True,
        "No deterministic syntax rewrite is registered; semantic reconstruction needs approval or stronger evidence.",
    ),
    "merge-conflict": (
        "merge-conflict-resolution",
        0,
        True,
        "Choosing the correct side of a conflict requires repository intent or human approval.",
    ),
    "missing-local-asset": (
        "asset-reconstruction",
        0,
        True,
        "The missing file contents cannot be inferred safely from the reference alone.",
    ),
}


def recommendations(findings: Sequence[Finding]) -> list[HealingRecommendation]:
    """Translate remaining findings into explicit next-healing instructions."""
    result: list[HealingRecommendation] = []
    for finding in findings:
        strategy, confidence, human_required, reason = _STRATEGIES.get(
            finding.code,
            (
                "unregistered-repair-strategy",
                0,
                True,
                "No evidence-backed deterministic repair strategy is registered for this finding.",
            ),
        )
        result.append(
            HealingRecommendation(
                finding_code=finding.code,
                path=finding.path,
                next_strategy=strategy,
                confidence=confidence,
                human_required=human_required,
                reason=reason,
            )
        )
    return result


def _recommendation_output(findings: Sequence[Finding]) -> str:
    return json.dumps([asdict(item) for item in recommendations(findings)], sort_keys=True)


def doctor_healing_run(
    original_run: Callable[..., RepairReport],
    engine: object,
    *,
    apply: bool = False,
) -> RepairReport:
    """Run bounded cumulative healing, then verify once and rollback on failure."""
    if not apply:
        return original_run(engine, apply=False)

    root = getattr(engine, "root")
    doctor = getattr(engine, "doctor")
    fixer = getattr(engine, "fixer")
    max_attempts = getattr(engine, "max_attempts")
    memory = getattr(engine, "memory")

    report = RepairReport(root=str(root), started_at=utc_now())
    snapshots: dict[str, bytes] = {}
    changed_paths: set[str] = set()
    previous_signatures: set[tuple[tuple[str, str | None, int | None], ...]] = set()

    for attempt in range(1, max_attempts + 1):
        report.attempts = attempt
        current = engine.diagnose()
        report.findings = current
        report.diagnosis = doctor.classify(current)

        if report.diagnosis == Verdict.HEALTHY:
            break

        signature = tuple(sorted((item.code, item.path, item.line) for item in current))
        if signature in previous_signatures:
            report.evidence.append(
                Evidence(
                    "Doctor healing progress guard",
                    False,
                    output="The same diagnosis remained after a healing cycle; unsafe looping was stopped.",
                )
            )
            break
        previous_signatures.add(signature)

        decision = engine.decide(current)
        if decision is None:
            report.evidence.append(
                Evidence(
                    "Doctor next healing recommendation",
                    True,
                    output=_recommendation_output(current),
                )
            )
            break

        selected = [
            item
            for item in current
            if item.severity == Severity.REPAIRABLE and item.path in decision.paths
        ]
        for rel in decision.paths:
            path = root / rel
            if path.is_file() and rel not in snapshots:
                snapshots[rel] = path.read_bytes()

        report.evidence.append(
            Evidence(
                f"Doctor healing cycle {attempt}: {', '.join(decision.paths)}",
                True,
                output=(
                    f"confidence={decision.confidence}% risk={decision.risk}; "
                    f"strategy findings={','.join(decision.finding_codes)}; {decision.reason}"
                ),
            )
        )
        repairs = fixer.apply(selected)
        report.repairs.extend(repairs)
        newly_changed = {item.path for item in repairs if item.changed}
        changed_paths.update(newly_changed)

        if not newly_changed:
            report.evidence.append(
                Evidence(
                    "Doctor healing strategy produced a change",
                    False,
                    output=_recommendation_output(current),
                )
            )
            break

    final_findings = engine.diagnose()
    report.findings = final_findings
    verification = engine._verification(final_findings)
    report.evidence.extend(verification)
    verified = bool(verification) and all(item.passed for item in verification)

    if verified:
        report.final_verdict = Verdict.PASS
        report.changed_files = sorted(changed_paths)
    else:
        for rel, content in snapshots.items():
            (root / rel).write_bytes(content)
        if snapshots:
            rolled_back = ", ".join(sorted(snapshots))
            report.evidence.append(
                Evidence(
                    "Rollback unverified healing session",
                    True,
                    output=rolled_back,
                )
            )
            # Keep the established evidence contract used by callers and older
            # tests while also exposing the more specific session-level event.
            report.evidence.append(
                Evidence(
                    "Rollback unverified repair",
                    True,
                    output=rolled_back,
                )
            )
        report.changed_files = []
        report.findings = engine.diagnose()
        report.final_verdict = Verdict.FAIL
        remaining = [item for item in report.findings if item.severity == Severity.CRITICAL]
        if remaining:
            report.evidence.append(
                Evidence(
                    "Doctor remaining capability requirements",
                    True,
                    output=_recommendation_output(remaining),
                )
            )

    report.finished_at = utc_now()
    memory.record(report)
    return report

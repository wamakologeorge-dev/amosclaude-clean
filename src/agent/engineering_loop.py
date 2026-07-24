"""Autonomous Engineering Loop: understand -> inspect -> plan -> execute -> verify -> learn -> report."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from time import monotonic
from typing import Any


class LoopPhase(str, Enum):
    UNDERSTAND = "understand"
    INSPECT = "inspect"
    PLAN = "plan"
    EXECUTE = "execute"
    VERIFY = "verify"
    LEARN = "learn"
    REPORT = "report"


@dataclass
class LoopEvent:
    phase: str
    status: str
    message: str
    elapsed_seconds: float
    evidence: list[str] = field(default_factory=list)


@dataclass
class ChangeProposal:
    path: str
    content: str
    reason: str = ""


@dataclass
class LoopOutcome:
    status: str
    objective: str
    success_criteria: list[str]
    plan: list[str]
    changed_files: list[str]
    checks: list[dict[str, Any]]
    events: list[LoopEvent]
    lessons: list[str]
    duration_seconds: float
    blocker: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AutonomousEngineeringLoop:
    """Bounded engineering cycle used by the single Amosclaud Autonomous orchestrator."""

    def __init__(self, *, analyzer, model, files, runtime, max_attempts: int = 2) -> None:
        self.analyzer = analyzer
        self.model = model
        self.files = files
        self.runtime = runtime
        self.max_attempts = max(1, min(max_attempts, 5))

    def run(self, *, objective: str, mode: str, authorized_writes: bool) -> LoopOutcome:
        started = monotonic()
        events: list[LoopEvent] = []
        changed: list[str] = []
        lessons: list[str] = []
        checks: list[dict[str, Any]] = []

        def record(phase: LoopPhase, status: str, message: str, evidence: list[str] | None = None) -> None:
            events.append(LoopEvent(phase.value, status, message, round(monotonic() - started, 3), evidence or []))

        criteria = [
            "Requested outcome is addressed",
            "Changes remain inside the designated workspace",
            "Verification produces evidence",
            "No success is reported while blocking checks fail",
        ]
        record(LoopPhase.UNDERSTAND, "passed", "Objective and success criteria established.", criteria)

        evidence = self.analyzer.inspect()
        record(LoopPhase.INSPECT, "passed", f"Inspected repository evidence ({len(evidence)} item(s)).", evidence[:20])

        if mode == "fix" and not authorized_writes:
            blocker = "Fix mode requires explicit write authorization"
            record(LoopPhase.PLAN, "blocked", blocker)
            outcome = self._finish(
                started, objective, criteria, [], changed, checks, events, lessons, blocker
            )
            outcome.status = "blocked"
            return outcome

        plan = self._plan(objective, evidence, mode)
        record(LoopPhase.PLAN, "passed", "Created a bounded engineering plan.", plan)

        if mode == "fix":
            try:
                proposals = self._proposals(objective, evidence)
                for proposal in proposals:
                    self.files.write(proposal.path, proposal.content, authorized=True)
                    changed.append(proposal.path)
                record(LoopPhase.EXECUTE, "passed", f"Applied {len(changed)} authorized file change(s).", changed)
            except Exception as exc:
                blocker = f"Execution stopped safely: {type(exc).__name__}: {exc}"
                record(LoopPhase.EXECUTE, "failed", blocker)
                return self._finish(started, objective, criteria, plan, changed, checks, events, lessons, blocker)
        else:
            record(LoopPhase.EXECUTE, "skipped", "Read-only mode; no files were changed.")

        for attempt in range(1, self.max_attempts + 1):
            checks = self.runtime.verify()
            failed = [item for item in checks if not item.get("passed")]
            record(LoopPhase.VERIFY, "failed" if failed else "passed", f"Verification attempt {attempt} completed.", [item.get("summary", "") for item in checks])
            if not failed:
                break
            if mode != "fix" or attempt == self.max_attempts:
                blocker = failed[0].get("summary") or "Verification failed"
                lessons.append(f"Do not report success until this blocker is resolved: {blocker}")
                record(LoopPhase.LEARN, "recorded", "Stored a failure lesson for the Academy.", lessons)
                return self._finish(started, objective, criteria, plan, changed, checks, events, lessons, blocker)
            record(LoopPhase.EXECUTE, "retry", "Verification failed; another bounded repair attempt is allowed.")

        lessons.append(f"Verified objective with {len(changed)} changed file(s) and {len(checks)} check(s).")
        record(LoopPhase.LEARN, "recorded", "Prepared verified lesson evidence for the Academy.", lessons)
        record(LoopPhase.REPORT, "passed", "Engineering loop completed with verification evidence.")
        return LoopOutcome("success", objective, criteria, plan, changed, checks, events, lessons, round(monotonic() - started, 3))

    def _plan(self, objective: str, evidence: list[str], mode: str) -> list[str]:
        if mode == "fix":
            return self.model.plan(objective, evidence)
        return ["Understand objective", "Inspect evidence", "Run deterministic verification", "Report exact results"]

    def _proposals(self, objective: str, evidence: list[str]) -> list[ChangeProposal]:
        raw = self.model.complete(objective, evidence).strip()
        if raw.startswith("```"):
            raw = "\n".join(raw.splitlines()[1:-1])
        payload = json.loads(raw)
        changes = payload.get("changes", []) if isinstance(payload, dict) else []
        if not isinstance(changes, list):
            raise ValueError("Model proposal must contain a changes list")
        proposals: list[ChangeProposal] = []
        for item in changes[:12]:
            if not isinstance(item, dict) or not isinstance(item.get("path"), str) or not isinstance(item.get("content"), str):
                raise ValueError("Every change requires path and complete content")
            proposals.append(ChangeProposal(item["path"], item["content"], str(item.get("reason", ""))))
        return proposals

    @staticmethod
    def _finish(started, objective, criteria, plan, changed, checks, events, lessons, blocker) -> LoopOutcome:
        events.append(LoopEvent(LoopPhase.REPORT.value, "failed" if blocker else "passed", "Engineering loop reported the final result.", round(monotonic() - started, 3), [blocker] if blocker else []))
        return LoopOutcome("failed" if blocker else "success", objective, criteria, plan, changed, checks, events, lessons, round(monotonic() - started, 3), blocker)

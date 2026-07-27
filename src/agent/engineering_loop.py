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
    """Bounded repair cycle used by the single Amosclaud Autonomous orchestrator."""

    def __init__(self, *, analyzer, model, files, runtime, max_attempts: int = 2) -> None:
        self.analyzer = analyzer
        self.model = model
        self.files = files
        self.runtime = runtime
        self.max_attempts = max(1, min(max_attempts, 5))

    def _inspect_evidence(self, objective: str) -> list[str]:
        """Use objective-aware analyzers while preserving older adapter contracts."""
        try:
            return self.analyzer.inspect(objective)
        except TypeError:
            return self.analyzer.inspect()

    def _verify_changes(self, changed: list[str]) -> list[dict[str, Any]]:
        """Use changed-file verification while preserving older runtime adapters."""
        try:
            return self.runtime.verify(changed_files=changed)
        except TypeError:
            return self.runtime.verify()

    def _apply_proposals(
        self,
        proposals: list[ChangeProposal],
        changed: list[str],
    ) -> list[str]:
        applied: list[str] = []
        for proposal in proposals:
            self.files.write(proposal.path, proposal.content, authorized=True)
            applied.append(proposal.path)
            if proposal.path not in changed:
                changed.append(proposal.path)
        return applied

    @staticmethod
    def _retry_evidence(
        repository_evidence: list[str],
        failed_checks: list[dict[str, Any]],
        attempt: int,
    ) -> list[str]:
        failure_evidence = [
            (
                f"ISOLATED VERIFICATION ATTEMPT {attempt} FAILED. "
                "The next proposal must correct these exact failures rather than "
                "repeat the previous patch."
            )
        ]
        for check in failed_checks[:8]:
            failure_evidence.append(
                json.dumps(
                    {
                        "name": check.get("name"),
                        "command": check.get("command"),
                        "exit_code": check.get("exit_code"),
                        "summary": check.get("summary"),
                        "output": str(check.get("output") or "")[-12_000:],
                        "isolated": check.get("isolated"),
                    },
                    ensure_ascii=False,
                )
            )
        return [*repository_evidence, *failure_evidence]

    def run(self, *, objective: str, mode: str, authorized_writes: bool) -> LoopOutcome:
        started = monotonic()
        events: list[LoopEvent] = []
        changed: list[str] = []
        lessons: list[str] = []
        checks: list[dict[str, Any]] = []

        def record(
            phase: LoopPhase,
            status: str,
            message: str,
            evidence: list[str] | None = None,
        ) -> None:
            events.append(
                LoopEvent(
                    phase.value,
                    status,
                    message,
                    round(monotonic() - started, 3),
                    evidence or [],
                )
            )

        criteria = [
            "Requested outcome is addressed",
            "Changes remain inside the designated workspace",
            "Verification runs inside the isolated runner and produces evidence",
            "No success is reported while blocking checks fail",
        ]
        record(
            LoopPhase.UNDERSTAND,
            "passed",
            "Objective and success criteria established.",
            criteria,
        )

        evidence = self._inspect_evidence(objective)
        record(
            LoopPhase.INSPECT,
            "passed",
            f"Inspected repository evidence ({len(evidence)} item(s)).",
            evidence[:20],
        )

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
                applied = self._apply_proposals(
                    self._proposals(objective, evidence),
                    changed,
                )
                record(
                    LoopPhase.EXECUTE,
                    "passed",
                    f"Applied {len(applied)} authorized file change(s).",
                    applied,
                )
            except Exception as exc:
                blocker = f"Execution stopped safely: {type(exc).__name__}: {exc}"
                record(LoopPhase.EXECUTE, "failed", blocker)
                return self._finish(
                    started,
                    objective,
                    criteria,
                    plan,
                    changed,
                    checks,
                    events,
                    lessons,
                    blocker,
                )
        else:
            record(
                LoopPhase.EXECUTE,
                "skipped",
                "Read-only mode; no files were changed.",
            )

        for attempt in range(1, self.max_attempts + 1):
            checks = self._verify_changes(changed)
            failed = [item for item in checks if not item.get("passed")]
            record(
                LoopPhase.VERIFY,
                "failed" if failed else "passed",
                f"Isolated verification attempt {attempt} completed.",
                [item.get("summary", "") for item in checks],
            )
            if not failed:
                break

            if mode != "fix" or attempt == self.max_attempts:
                blocker = failed[0].get("summary") or "Verification failed"
                lessons.append(
                    f"Do not report success until this blocker is resolved: {blocker}"
                )
                record(
                    LoopPhase.LEARN,
                    "recorded",
                    "Stored a failure lesson for the Academy.",
                    lessons,
                )
                return self._finish(
                    started,
                    objective,
                    criteria,
                    plan,
                    changed,
                    checks,
                    events,
                    lessons,
                    blocker,
                )

            retry_objective = (
                f"{objective}\n\n"
                "The previous authorized repair failed isolated verification. "
                "Read the exact compiler, build, and test logs in the evidence, "
                "diagnose the root cause, and return a corrected complete-file proposal."
            )
            retry_evidence = self._retry_evidence(evidence, failed, attempt)
            try:
                applied = self._apply_proposals(
                    self._proposals(retry_objective, retry_evidence),
                    changed,
                )
            except Exception as exc:
                blocker = f"Corrective repair stopped safely: {type(exc).__name__}: {exc}"
                lessons.append(
                    f"Verification logs were available but correction failed: {blocker}"
                )
                record(LoopPhase.EXECUTE, "failed", blocker)
                return self._finish(
                    started,
                    objective,
                    criteria,
                    plan,
                    changed,
                    checks,
                    events,
                    lessons,
                    blocker,
                )
            record(
                LoopPhase.EXECUTE,
                "retry",
                (
                    "Verification failed; read the isolated logs and applied a "
                    f"corrective repair for attempt {attempt + 1}."
                ),
                applied,
            )

        lessons.append(
            f"Verified objective with {len(changed)} changed file(s) and {len(checks)} check(s)."
        )
        record(
            LoopPhase.LEARN,
            "recorded",
            "Prepared verified lesson evidence for the Academy.",
            lessons,
        )
        record(
            LoopPhase.REPORT,
            "passed",
            "Engineering loop completed with isolated verification evidence.",
        )
        return LoopOutcome(
            "success",
            objective,
            criteria,
            plan,
            changed,
            checks,
            events,
            lessons,
            round(monotonic() - started, 3),
        )

    def _plan(self, objective: str, evidence: list[str], mode: str) -> list[str]:
        if mode == "fix":
            return self.model.plan(objective, evidence)
        return [
            "Understand objective",
            "Inspect evidence",
            "Run deterministic verification in an isolated container",
            "Report exact results",
        ]

    def _proposals(self, objective: str, evidence: list[str]) -> list[ChangeProposal]:
        raw = self.model.complete(objective, evidence).strip()
        payload = self._json_payload(raw)
        changes = payload.get("changes", []) if isinstance(payload, dict) else []
        if not isinstance(changes, list) or not changes:
            raise ValueError("Model proposal must contain at least one change")
        proposals: list[ChangeProposal] = []
        seen: set[str] = set()
        for item in changes[:8]:
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("path"), str)
                or not isinstance(item.get("content"), str)
            ):
                raise ValueError("Every change requires path and complete content")
            path = item["path"].strip().replace("\\", "/")
            if not path or path in seen:
                raise ValueError("Every proposed path must be unique and non-empty")
            seen.add(path)
            proposals.append(
                ChangeProposal(path, item["content"], str(item.get("reason", "")))
            )
        return proposals

    @staticmethod
    def _json_payload(raw: str) -> dict[str, Any]:
        if raw.startswith("```"):
            lines = raw.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            raw = "\n".join(lines).strip()
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            start = raw.find("{")
            end = raw.rfind("}")
            if start < 0 or end <= start:
                raise ValueError("Model proposal did not contain a JSON object")
            payload = json.loads(raw[start : end + 1])
        if not isinstance(payload, dict):
            raise ValueError("Model proposal must be a JSON object")
        return payload

    @staticmethod
    def _finish(
        started,
        objective,
        criteria,
        plan,
        changed,
        checks,
        events,
        lessons,
        blocker,
    ) -> LoopOutcome:
        events.append(
            LoopEvent(
                LoopPhase.REPORT.value,
                "failed" if blocker else "passed",
                "Engineering loop reported the final result.",
                round(monotonic() - started, 3),
                [blocker] if blocker else [],
            )
        )
        return LoopOutcome(
            "failed" if blocker else "success",
            objective,
            criteria,
            plan,
            changed,
            checks,
            events,
            lessons,
            round(monotonic() - started, 3),
            blocker,
        )

"""Single-file Amosclaud Autonomous Cloud Agent engine.

This module implements one public agent backed by five internal engines:

1. Receive/understand
2. Perceive/inspect
3. Plan
4. Act
5. Verify/report

Each engine writes a structured model-log-service event. The logs contain
objectives, decisions, actions, and evidence; they never contain hidden model
reasoning or secrets.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from amoscloud_ai.engineering_agent import EngineeringAgentError, run_engineering_agent


ENGINE_NAMES = (
    "agent-1-receive-engine",
    "agent-2-perception-engine",
    "agent-3-planning-engine",
    "agent-4-action-engine",
    "agent-5-verification-engine",
)

LOG_SERVICE_NAMES = (
    "agent-1-model-log-service-engine",
    "agent-2-model-log-service-engine",
    "agent-3-model-log-service-engine",
    "agent-4-model-log-service-engine",
    "agent-5-model-log-service-engine",
)

ALLOWED_MODES = {"autonomous-check", "build", "fix", "deploy", "monitor"}
WRITE_MODES = {"fix"}
SKIP_PARTS = {".git", ".amosclaud", ".venv", "venv", "node_modules", "__pycache__", "dist", "build", "data"}
SOURCE_SUFFIXES = {".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".css", ".json", ".md", ".yml", ".yaml", ".toml", ".sh"}
MAX_DISCOVERY_FILES = 400
MAX_EVIDENCE_LINES = 80


@dataclass
class AgentEvent:
    engine: str
    log_service: str
    status: str
    message: str
    evidence: list[str] = field(default_factory=list)
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    finished_at: str | None = None
    duration_ms: int | None = None

    def finish(self, status: str, message: str, evidence: list[str] | None = None, started: float | None = None) -> "AgentEvent":
        self.status = status
        self.message = message
        if evidence is not None:
            self.evidence = evidence[:MAX_EVIDENCE_LINES]
        self.finished_at = datetime.now(timezone.utc).isoformat()
        if started is not None:
            self.duration_ms = int((time.monotonic() - started) * 1000)
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "engine": self.engine,
            "log_service": self.log_service,
            "status": self.status,
            "message": self.message,
            "evidence": self.evidence,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
        }


@dataclass
class AgenticCloudRun:
    run_id: str
    objective: str
    mode: str
    status: str
    summary: str
    authorized_writes: bool
    events: list[AgentEvent]
    changed_files: list[str] = field(default_factory=list)
    checks: list[dict[str, Any]] = field(default_factory=list)
    plan: list[str] = field(default_factory=list)
    memory: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "objective": self.objective,
            "mode": self.mode,
            "status": self.status,
            "summary": self.summary,
            "authorized_writes": self.authorized_writes,
            "plan": self.plan,
            "changed_files": self.changed_files,
            "checks": self.checks,
            "memory": self.memory,
            "events": [event.to_dict() for event in self.events],
        }


class StructuredModelLogService:
    """Append-only per-run JSONL logging for all five engines."""

    def __init__(self, repository_root: Path, run_id: str) -> None:
        configured = os.getenv("AMOSCLAUD_AGENT_LOG_DIR", "").strip()
        base = Path(configured) if configured else repository_root / ".amosclaud" / "agent-logs"
        self.path = base / f"{run_id}.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, event: AgentEvent) -> None:
        payload = {"type": "agent-engine-event", **event.to_dict()}
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")


class AmosclaudAgenticCloudEngine:
    """One cloud agent orchestrating five internal engines in one file."""

    def __init__(self, repository_root: Path) -> None:
        self.root = repository_root.resolve()

    def run(self, objective: str, mode: str, metadata: dict[str, Any] | None = None) -> AgenticCloudRun:
        metadata = dict(metadata or {})
        mode = (mode or "autonomous-check").strip().lower()
        if mode not in ALLOWED_MODES:
            raise ValueError(f"Unsupported agent mode: {mode}")
        objective = " ".join((objective or "").split())
        if not objective:
            raise ValueError("An autonomous objective is required")

        run_id = uuid.uuid4().hex
        log_service = StructuredModelLogService(self.root, run_id)
        events: list[AgentEvent] = []
        state: dict[str, Any] = {
            "run_id": run_id,
            "objective": objective,
            "mode": mode,
            "metadata": metadata,
            "authorized_writes": mode in WRITE_MODES and bool(metadata.get("apply_changes", True)),
            "plan": [],
            "changed_files": [],
            "checks": [],
            "memory": [],
        }

        stages: list[Callable[[dict[str, Any]], AgentEvent]] = [
            self._engine_receive,
            self._engine_perceive,
            self._engine_plan,
            self._engine_act,
            self._engine_verify,
        ]

        for index, stage in enumerate(stages):
            try:
                event = stage(state)
            except Exception as exc:
                event = AgentEvent(
                    engine=ENGINE_NAMES[index],
                    log_service=LOG_SERVICE_NAMES[index],
                    status="failed",
                    message=f"{type(exc).__name__}: {exc}",
                    evidence=["The agent stopped safely. No later engine was executed."],
                    finished_at=datetime.now(timezone.utc).isoformat(),
                )
                events.append(event)
                log_service.write(event)
                return AgenticCloudRun(
                    run_id=run_id,
                    objective=objective,
                    mode=mode,
                    status="failed",
                    summary=f"Autonomous cloud agent stopped in {event.engine}: {event.message}",
                    authorized_writes=state["authorized_writes"],
                    events=events,
                    changed_files=state["changed_files"],
                    checks=state["checks"],
                    plan=state["plan"],
                    memory=state["memory"],
                )
            events.append(event)
            log_service.write(event)
            if event.status == "failed":
                break

        failed = any(event.status == "failed" for event in events)
        blocking_checks = [check for check in state["checks"] if not check.get("passed", False)]
        status = "failed" if failed or blocking_checks else "success"
        if status == "success":
            summary = "Amosclaud Autonomous Cloud Agent completed the objective with verification evidence."
        else:
            summary = f"Amosclaud Autonomous Cloud Agent needs attention: {len(blocking_checks)} blocking verification result(s)."

        return AgenticCloudRun(
            run_id=run_id,
            objective=objective,
            mode=mode,
            status=status,
            summary=summary,
            authorized_writes=state["authorized_writes"],
            events=events,
            changed_files=state["changed_files"],
            checks=state["checks"],
            plan=state["plan"],
            memory=state["memory"],
        )

    def _event(self, index: int) -> tuple[AgentEvent, float]:
        return AgentEvent(ENGINE_NAMES[index], LOG_SERVICE_NAMES[index], "running", "Engine started"), time.monotonic()

    def _engine_receive(self, state: dict[str, Any]) -> AgentEvent:
        event, started = self._event(0)
        objective = state["objective"]
        mode = state["mode"]
        success_criteria = state["metadata"].get("success_criteria") or "Complete the requested outcome and provide verifiable evidence."
        state["success_criteria"] = str(success_criteria)
        return event.finish(
            "passed",
            "Objective received and normalized by the autonomous core.",
            [f"Mode: {mode}", f"Objective: {objective}", f"Success criteria: {success_criteria}", f"Write authorization: {state['authorized_writes']}"],
            started,
        )

    def _engine_perceive(self, state: dict[str, Any]) -> AgentEvent:
        event, started = self._event(1)
        files: list[str] = []
        for path in self.root.rglob("*"):
            if len(files) >= MAX_DISCOVERY_FILES:
                break
            if not path.is_file() or path.suffix.lower() not in SOURCE_SUFFIXES:
                continue
            relative = path.relative_to(self.root)
            if any(part in SKIP_PARTS for part in relative.parts):
                continue
            files.append(relative.as_posix())
        state["repository_files"] = files
        git_evidence = self._command(["git", "status", "--short"], 12) if (self.root / ".git").exists() else (0, "Production workspace has no Git metadata.")
        state["git_status"] = git_evidence[1]
        return event.finish(
            "passed",
            "Repository and runtime evidence collected.",
            [f"Discovered {len(files)} supported source files.", *files[:20], git_evidence[1] or "Workspace clean."],
            started,
        )

    def _engine_plan(self, state: dict[str, Any]) -> AgentEvent:
        event, started = self._event(2)
        mode = state["mode"]
        if mode in {"build", "fix"}:
            engineering = run_engineering_agent(
                self.root,
                state["objective"],
                workspace_path=state["metadata"].get("workspace_path"),
                apply_changes=False,
            )
            state["engineering_plan"] = engineering
            state["plan"] = [
                f"{change.status}: {change.path}"
                for change in engineering.changes
            ] or [engineering.summary]
            state["memory"].append(f"Recalled and updated engineering memory for run {engineering.run_id}.")
            evidence = [engineering.summary, *state["plan"], *engineering.evidence]
        else:
            state["plan"] = self._deterministic_plan(mode)
            evidence = state["plan"]
        return event.finish("passed", "A bounded execution plan was prepared.", evidence, started)

    def _engine_act(self, state: dict[str, Any]) -> AgentEvent:
        event, started = self._event(3)
        mode = state["mode"]
        if mode == "fix":
            if not state["authorized_writes"]:
                return event.finish("failed", "Fix mode requires explicit write authorization.", ["Set metadata.apply_changes=true."], started)
            engineering = run_engineering_agent(
                self.root,
                state["objective"],
                workspace_path=state["metadata"].get("workspace_path"),
                apply_changes=True,
            )
            state["engineering_run"] = engineering
            state["changed_files"] = [change.path for change in engineering.changes if change.status == "written"]
            state["checks"].extend(engineering.checks)
            return event.finish(
                "passed",
                "Authorized workspace changes were processed by the action engine.",
                [engineering.summary, *[f"{change.status}: {change.path}" for change in engineering.changes], *engineering.evidence],
                started,
            )
        if mode == "deploy":
            return event.finish("warning", "Deployment was prepared but not executed by this repository engine.", ["Use the controlled deployment service for production release actions."], started)
        return event.finish("passed", "No file-writing action was required or authorized.", [f"Mode {mode} remained read-only."], started)

    def _engine_verify(self, state: dict[str, Any]) -> AgentEvent:
        event, started = self._event(4)
        compile_code, compile_output = self._command([sys.executable, "-m", "py_compile", str(self.root / "amoscloud_ai" / "agentic_cloud_engine.py")], 30)
        compile_check = {"name": "agentic-engine-compile", "passed": compile_code == 0, "output": compile_output}
        state["checks"].append(compile_check)

        if not os.environ.get("PYTEST_CURRENT_TEST") and (self.root / "tests").is_dir():
            test_code, test_output = self._command([sys.executable, "-m", "pytest", "-q", "tests/test_server.py"], 90)
            state["checks"].append({"name": "focused-server-tests", "passed": test_code == 0, "output": test_output[-6000:]})

        failed = [check for check in state["checks"] if not check.get("passed", False)]
        evidence = [
            f"{check.get('name')}: {'passed' if check.get('passed') else 'failed'}"
            for check in state["checks"]
        ]
        evidence.extend(f"Changed: {path}" for path in state["changed_files"])
        return event.finish(
            "failed" if failed else "passed",
            "Verification found blocking results." if failed else "Verification completed successfully.",
            evidence or ["No executable verification was required."],
            started,
        )

    def _command(self, args: list[str], timeout: int) -> tuple[int, str]:
        try:
            result = subprocess.run(args, cwd=self.root, text=True, capture_output=True, timeout=timeout, check=False)
        except (OSError, subprocess.SubprocessError) as exc:
            return 127, f"{type(exc).__name__}: {exc}"
        output = (result.stdout + "\n" + result.stderr).strip()
        return result.returncode, output[-8000:]

    @staticmethod
    def _deterministic_plan(mode: str) -> list[str]:
        plans = {
            "autonomous-check": ["Inspect repository state", "Run verification", "Report blockers and evidence"],
            "monitor": ["Inspect runtime health", "Evaluate current evidence", "Report status and recommended action"],
            "deploy": ["Validate release readiness", "Request controlled deployment service", "Verify post-deployment health"],
        }
        return plans.get(mode, ["Inspect", "Plan", "Verify", "Report"])


def run_agentic_cloud_engine(repository_root: Path, objective: str, mode: str, metadata: dict[str, Any] | None = None) -> AgenticCloudRun:
    """Public entry point used by the autonomous runtime."""
    return AmosclaudAgenticCloudEngine(repository_root).run(objective, mode, metadata)

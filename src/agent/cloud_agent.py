"""Conversational Cloud Agent backed by the one Amosclaud Autonomous brain."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import urlparse

from .actions import run_autonomous
from .model import AutonomousModelGateway
from .rollimage import RollImageEngine


@dataclass
class ResultPointer:
    label: str
    location: str
    platform: str
    kind: str


@dataclass
class CloudAgentReply:
    reply: str
    status: str
    rollimage: dict[str, Any]
    instruction_detected: bool
    requires_authorization: bool
    plan: list[str] = field(default_factory=list)
    what_can_go_wrong: list[str] = field(default_factory=list)
    recommended_solution: list[str] = field(default_factory=list)
    easier_way: list[str] = field(default_factory=list)
    execution_result: dict[str, Any] | None = None
    result_pointers: list[ResultPointer] = field(default_factory=list)
    next_step: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AmosclaudCloudAgent:
    """Explain, plan, execute authorized work, verify, and point to results."""

    ACTION_WORDS = {"build", "create", "fix", "change", "delete", "deploy", "commit", "merge", "run", "test", "review", "monitor"}
    WRITE_WORDS = {"build", "create", "fix", "change", "delete", "deploy", "commit", "merge"}

    def __init__(self) -> None:
        self.model = AutonomousModelGateway()
        self.rollimage = RollImageEngine()

    def reply(
        self,
        message: str,
        *,
        evidence: list[str] | None = None,
        result_locations: list[str] | None = None,
        execute: bool = False,
        authorized_writes: bool = False,
        workspace: str = ".",
    ) -> CloudAgentReply:
        evidence = evidence or []
        image = self.rollimage.create(message, evidence)
        words = {word.strip(".,!?():;").lower() for word in message.split()}
        actionable = bool(words & self.ACTION_WORDS)
        requires_authorization = bool(words & self.WRITE_WORDS)
        mode = self._mode(words)

        plan = self._plan(mode, actionable)
        risks = self._risks(mode, requires_authorization, bool(evidence))
        solution = self._solution(mode)
        easier = self._easier_way(mode)
        pointers = [self._pointer(item) for item in (result_locations or []) if item.strip()]
        execution_result: dict[str, Any] | None = None

        if execute and actionable:
            if requires_authorization and not authorized_writes:
                answer = "I prepared the plan, but execution is waiting for explicit write authorization."
            else:
                execution_result = run_autonomous(
                    objective=message,
                    mode=mode,
                    authorized_writes=authorized_writes,
                    workspace=workspace,
                )
                answer = self._execution_summary(execution_result)
                pointers.extend(self._result_pointers(execution_result))
        elif self.model.available():
            prompt = (
                "Act as Amosclaud Agent Assistant. Answer the user's question directly, explain risks, "
                "recommend the right solution and an easier safe alternative, and never claim an action completed "
                "without verification evidence."
            )
            answer = self.model.complete(message, [prompt, self.rollimage.system_context(image), *evidence])
        elif actionable:
            answer = (
                "I understand the instruction and prepared a safe plan. "
                + ("Applying changes requires explicit authorization. " if requires_authorization else "")
                + "The cloud model connection is not ready, so I will not claim the work is complete."
            )
        else:
            answer = (
                "I can answer questions, explain what may fail, recommend the right solution, show an easier path, "
                "follow instructions, execute authorized jobs, verify results, and point you to the result location."
            )

        return CloudAgentReply(
            reply=answer,
            status=self._status(execution_result),
            rollimage=image.to_dict(),
            instruction_detected=actionable,
            requires_authorization=requires_authorization,
            plan=plan,
            what_can_go_wrong=risks,
            recommended_solution=solution,
            easier_way=easier,
            execution_result=execution_result,
            result_pointers=self._dedupe_pointers(pointers),
            next_step=self._next_step(execute, actionable, requires_authorization, authorized_writes, execution_result),
        )

    @staticmethod
    def _mode(words: set[str]) -> str:
        for candidate in ("deploy", "fix", "test", "review", "monitor", "build"):
            if candidate in words:
                return candidate
        return "plan"

    @staticmethod
    def _plan(mode: str, actionable: bool) -> list[str]:
        if not actionable:
            return ["Understand the question", "Use available evidence", "Explain the answer clearly", "Show the next useful step"]
        return [
            "Understand the requested outcome",
            "Inspect repository and platform evidence",
            "Identify risks and required authorization",
            f"Run the bounded {mode} workflow",
            "Verify the result before reporting success",
            "Show exactly where the result can be opened",
        ]

    @staticmethod
    def _risks(mode: str, requires_authorization: bool, has_evidence: bool) -> list[str]:
        risks = []
        if not has_evidence:
            risks.append("A decision made without logs, files, or runtime evidence may target the wrong cause.")
        if requires_authorization:
            risks.append("A write, deployment, commit, or merge without authorization could change production unexpectedly.")
        if mode in {"fix", "build", "deploy"}:
            risks.append("A change can pass one check but still break another service unless integration tests run.")
        risks.append("Reporting success before verification would hide unresolved blockers.")
        return risks

    @staticmethod
    def _solution(mode: str) -> list[str]:
        return [
            "Collect the smallest complete evidence packet first.",
            "Use the single Autonomous Engineering Loop instead of creating a disconnected path.",
            "Keep writes authorization-gated and workspace-isolated.",
            f"Run focused checks for the {mode} operation and preserve their output.",
            "Return a truthful status and direct result location.",
        ]

    @staticmethod
    def _easier_way(mode: str) -> list[str]:
        return [
            "Start in plan mode so the Agent can explain the work without changing files.",
            "Approve only the exact write step after reviewing the plan.",
            f"Use one focused {mode} job with a job ID instead of several manual paths.",
            "Open the returned Amosclaud path or external platform link to inspect the result.",
        ]

    @staticmethod
    def _execution_summary(result: dict[str, Any]) -> str:
        status = result.get("status", "unknown")
        blocker = result.get("blocker")
        if status == "success":
            return "The authorized job completed and verification evidence is attached below."
        if blocker:
            return f"The job did not reach success. Blocker: {blocker}"
        return f"The job finished with status: {status}."

    @staticmethod
    def _pointer(location: str) -> ResultPointer:
        value = location.strip()
        parsed = urlparse(value)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            platform = parsed.netloc.lower()
            return ResultPointer(label=f"Open result on {platform}", location=value, platform=platform, kind="external")
        path = value if value.startswith("/") else f"/{value}"
        return ResultPointer(label="Open result in Amosclaud", location=path, platform="amosclaud.com", kind="internal")

    def _result_pointers(self, result: dict[str, Any]) -> list[ResultPointer]:
        pointers: list[ResultPointer] = []
        for path in result.get("changed_files", []) or []:
            pointers.append(ResultPointer("Open changed file in Amosclaud workspace", str(path), "amosclaud.com", "file"))
        for key in ("url", "display_url", "pull_request_url", "issue_url", "deployment_url"):
            value = result.get(key)
            if isinstance(value, str) and value:
                pointers.append(self._pointer(value))
        return pointers

    @staticmethod
    def _dedupe_pointers(items: list[ResultPointer]) -> list[ResultPointer]:
        seen: set[str] = set()
        output: list[ResultPointer] = []
        for item in items:
            if item.location in seen:
                continue
            seen.add(item.location)
            output.append(item)
        return output[:20]

    def _status(self, result: dict[str, Any] | None) -> str:
        if result is not None:
            return str(result.get("status", "unknown"))
        return "ready" if self.model.available() else "degraded"

    @staticmethod
    def _next_step(execute: bool, actionable: bool, requires_authorization: bool, authorized: bool, result: dict[str, Any] | None) -> str:
        if result:
            return "Open a result pointer and review the verification checks."
        if actionable and requires_authorization and not authorized:
            return "Review the plan, then provide explicit authorization for the exact write operation."
        if actionable and not execute:
            return "Set execute=true when you are ready for the Agent to run the job."
        return "Ask a question or give the Agent a specific outcome to achieve."


def chat_with_autonomous(
    message: str,
    evidence: list[str] | None = None,
    result_locations: list[str] | None = None,
    execute: bool = False,
    authorized_writes: bool = False,
    workspace: str = ".",
) -> dict[str, Any]:
    return AmosclaudCloudAgent().reply(
        message,
        evidence=evidence,
        result_locations=result_locations,
        execute=execute,
        authorized_writes=authorized_writes,
        workspace=workspace,
    ).to_dict()

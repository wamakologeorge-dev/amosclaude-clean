from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol, Sequence


@dataclass(slots=True)
class ToolResult:
    ok: bool
    output: str
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Tool:
    name: str
    description: str
    handler: Callable[[Mapping[str, Any]], ToolResult]
    requires_approval: bool = False


@dataclass(slots=True)
class AgentStep:
    thought: str
    tool: str | None = None
    arguments: dict[str, Any] = field(default_factory=dict)
    final_answer: str | None = None


@dataclass(slots=True)
class AgentResult:
    objective: str
    status: str
    answer: str
    iterations: int
    evidence: list[dict[str, Any]] = field(default_factory=list)


class ModelProvider(Protocol):
    def next_step(
        self,
        *,
        objective: str,
        history: Sequence[dict[str, Any]],
        tools: Sequence[Tool],
        memory: Sequence[str],
    ) -> AgentStep: ...


class MemoryProvider(Protocol):
    def recall(self, objective: str, *, limit: int = 8) -> Sequence[str]: ...

    def record(self, objective: str, result: AgentResult) -> None: ...


class AgentRuntime:
    """Bounded observe-plan-act-verify loop for Amosclaud agents."""

    def __init__(
        self,
        model: ModelProvider,
        tools: Sequence[Tool],
        *,
        memory: MemoryProvider | None = None,
        approval: Callable[[Tool, Mapping[str, Any]], bool] | None = None,
        max_iterations: int = 20,
    ) -> None:
        if max_iterations < 1:
            raise ValueError("max_iterations must be positive")
        self.model = model
        self.tools = {tool.name: tool for tool in tools}
        self.memory = memory
        self.approval = approval
        self.max_iterations = max_iterations

    def run(self, objective: str) -> AgentResult:
        objective = objective.strip()
        if not objective:
            raise ValueError("objective is required")

        history: list[dict[str, Any]] = []
        evidence: list[dict[str, Any]] = []
        memories = list(self.memory.recall(objective) if self.memory else [])

        for iteration in range(1, self.max_iterations + 1):
            step = self.model.next_step(
                objective=objective,
                history=history,
                tools=list(self.tools.values()),
                memory=memories,
            )
            history.append({"type": "model", "step": step})

            if step.final_answer is not None:
                result = AgentResult(
                    objective=objective,
                    status="completed",
                    answer=step.final_answer,
                    iterations=iteration,
                    evidence=evidence,
                )
                if self.memory:
                    self.memory.record(objective, result)
                return result

            if not step.tool:
                return self._failed(objective, iteration, evidence, "Model returned no tool or final answer")

            tool = self.tools.get(step.tool)
            if tool is None:
                history.append({"type": "error", "error": f"Unknown tool: {step.tool}"})
                continue

            if tool.requires_approval:
                approved = bool(self.approval and self.approval(tool, step.arguments))
                if not approved:
                    history.append({"type": "observation", "tool": tool.name, "ok": False, "output": "Approval denied"})
                    continue

            try:
                observation = tool.handler(step.arguments)
            except Exception as exc:  # tool failures are observations, not runtime crashes
                observation = ToolResult(ok=False, output=f"{type(exc).__name__}: {exc}")

            history.append(
                {
                    "type": "observation",
                    "tool": tool.name,
                    "ok": observation.ok,
                    "output": observation.output,
                    "evidence": observation.evidence,
                }
            )
            if observation.evidence:
                evidence.append({"tool": tool.name, **observation.evidence})

        return self._failed(objective, self.max_iterations, evidence, "Maximum iterations reached")

    def _failed(self, objective: str, iterations: int, evidence: list[dict[str, Any]], answer: str) -> AgentResult:
        result = AgentResult(objective, "failed", answer, iterations, evidence)
        if self.memory:
            self.memory.record(objective, result)
        return result

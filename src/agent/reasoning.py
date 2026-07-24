"""Bounded ReAct decision models for auditable agent control."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

DecisionKind = Literal["act", "finish", "blocked"]


@dataclass(frozen=True)
class ActionRequest:
    tool: str
    arguments: dict[str, Any] = field(default_factory=dict)
    purpose: str = ""


@dataclass(frozen=True)
class ReactDecision:
    kind: DecisionKind
    reason: str
    action: ActionRequest | None = None
    answer: str = ""

    def __post_init__(self) -> None:
        if self.kind == "act" and self.action is None:
            raise ValueError("act decisions require an action")
        if self.kind != "act" and self.action is not None:
            raise ValueError("only act decisions may contain an action")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

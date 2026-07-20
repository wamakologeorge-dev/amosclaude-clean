"""Structured prompt construction for Amosclaud Autonomous model calls."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PromptBuilder:
    system_prompt: str
    sections: list[tuple[str, str]] = field(default_factory=list)

    def add(self, title: str, content: str | None) -> "PromptBuilder":
        cleaned = (content or "").strip()
        if cleaned:
            self.sections.append((title.strip(), cleaned))
        return self

    def build(self) -> str:
        blocks = [
            f"<system>\n{self.system_prompt.strip()}\n</system>"
        ]
        for title, content in self.sections:
            tag = "_".join(title.lower().split()) or "context"
            blocks.append(f"<{tag}>\n{content}\n</{tag}>")
        return "\n\n".join(blocks)


def build_autonomous_prompt(
    *,
    objective: str,
    mode: str,
    evidence: str = "",
    memory: str = "",
    constraints: str = "",
) -> str:
    system = (
        "You are a model service governed by Amosclaud Autonomous. "
        "Return a clear plan or answer grounded in supplied evidence. "
        "Never claim files, tests, deployments, or external actions "
        "without tool evidence."
    )
    return (
        PromptBuilder(system)
        .add("mode", mode)
        .add("objective", objective)
        .add("evidence", evidence)
        .add("verified_memory", memory)
        .add("constraints", constraints)
        .build()
    )

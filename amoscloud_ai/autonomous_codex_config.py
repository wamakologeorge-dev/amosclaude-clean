"""Configuration, skills, and controlled tools for the Amosclaud autonomous agent."""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    category: str
    write_capable: bool = False
    approval_required: bool = False
    enabled: bool = True


@dataclass(frozen=True)
class SkillDefinition:
    name: str
    title: str
    mission: str
    phases: tuple[str, ...]
    tools: tuple[str, ...]
    default_write_policy: str = "deny"


@dataclass(frozen=True)
class AutonomousCodexConfiguration:
    version: str = "1.0"
    planning_required: bool = True
    verification_required: bool = True
    rollback_on_failed_verification: bool = True
    max_iterations: int = 8
    max_changed_files: int = 12
    max_tool_calls: int = 40
    default_skill: str = "engineering"
    external_adapters_allowed: bool = False
    skills: tuple[SkillDefinition, ...] = field(default_factory=tuple)
    tools: tuple[ToolDefinition, ...] = field(default_factory=tuple)

    def public_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["provider"] = {
            "model_network_configured": bool(os.getenv("AMOSCLAUD_NETWORK_OWNER_USER_ID", "").strip()),
            "self_hosted_configured": bool(os.getenv("AMOSCLAUD_MODEL_URL", "").strip()),
            "amosclaud_api_configured": bool(
                os.getenv("AMOSCLAUD_API_URL", "").strip()
                and os.getenv("AMOSCLAUD_API_KEY", "").strip()
            ),
            "openai_configured": bool(os.getenv("OPENAI_API_KEY", "").strip()),
            "external_adapters_allowed": self.external_adapters_allowed,
        }
        return data


TOOLS = (
    ToolDefinition("repository.read", "Read repository files and instructions.", "repository"),
    ToolDefinition("repository.search", "Search code, configuration, and documentation.", "repository"),
    ToolDefinition("repository.write", "Create or update approved repository files.", "repository", True, True),
    ToolDefinition("repository.diff", "Inspect proposed and applied changes.", "repository"),
    ToolDefinition("shell.safe", "Run allowlisted compile, test, and inspection commands.", "execution"),
    ToolDefinition("tests.run", "Run focused and repository test suites.", "verification"),
    ToolDefinition("health.inspect", "Inspect web, worker, model, and storage readiness.", "operations"),
    ToolDefinition("pipeline.inspect", "Inspect autonomous pipeline state and evidence.", "operations"),
    ToolDefinition("deployment.prepare", "Prepare a deployment plan and rollback criteria.", "deployment", True, True),
    ToolDefinition("memory.recall", "Recall relevant repository lessons and prior outcomes.", "memory"),
    ToolDefinition("memory.store", "Store concise verified lessons from completed work.", "memory", True),
    ToolDefinition("github.app", "Read GitHub App events (pushes, pull requests, issues) recorded by the platform.", "integration"),
    ToolDefinition("web.research", "Research public technical documentation when enabled.", "research"),
)

SKILLS = (
    SkillDefinition(
        name="engineering",
        title="Codex Engineering Skill",
        mission="Understand a software objective, inspect the repository, plan minimal changes, execute authorized edits, test, review the diff, and report evidence.",
        phases=("receive", "inspect", "plan", "approve", "act", "verify", "review", "report"),
        tools=(
            "repository.read", "repository.search", "repository.write", "repository.diff",
            "shell.safe", "tests.run", "memory.recall", "memory.store",
        ),
        default_write_policy="explicit-or-fix-mode",
    ),
    SkillDefinition(
        name="research-operations",
        title="Claude-style Research and Operations Skill",
        mission="Analyze questions and operational incidents, gather evidence, compare options, inspect health and pipelines, and produce a clear recommendation without claiming unverified actions.",
        phases=("receive", "clarify", "research", "analyze", "plan", "verify", "report"),
        tools=(
            "repository.read", "repository.search", "health.inspect", "pipeline.inspect",
            "web.research", "memory.recall", "memory.store", "deployment.prepare",
        ),
        default_write_policy="deny",
    ),
)


def get_autonomous_codex_configuration() -> AutonomousCodexConfiguration:
    return AutonomousCodexConfiguration(
        max_iterations=max(1, min(int(os.getenv("AMOSCLAUD_AGENT_MAX_ITERATIONS", "8")), 25)),
        max_changed_files=max(1, min(int(os.getenv("AMOSCLAUD_AGENT_MAX_CHANGED_FILES", "12")), 50)),
        max_tool_calls=max(5, min(int(os.getenv("AMOSCLAUD_AGENT_MAX_TOOL_CALLS", "40")), 200)),
        default_skill=os.getenv("AMOSCLAUD_AGENT_DEFAULT_SKILL", "engineering").strip() or "engineering",
        external_adapters_allowed=os.getenv("AMOSCLAUD_ALLOW_EXTERNAL_ADAPTERS", "false").strip().lower()
        in {"1", "true", "yes", "on"},
        skills=SKILLS,
        tools=TOOLS,
    )


def select_skill(objective: str, requested: str | None = None) -> SkillDefinition:
    config = get_autonomous_codex_configuration()
    name = (requested or "").strip().lower()
    if name:
        for skill in config.skills:
            if skill.name == name:
                return skill
        raise ValueError(f"Unknown autonomous skill: {name}")
    text = objective.lower()
    research_terms = ("explain", "research", "compare", "investigate", "monitor", "health", "incident", "why")
    selected = "research-operations" if any(term in text for term in research_terms) else config.default_skill
    return next((skill for skill in config.skills if skill.name == selected), config.skills[0])

from __future__ import annotations

from typing import Any

from amoscloud_ai.autonomous_codex_config import (
    AutonomousCodexConfiguration,
    SkillDefinition,
    ToolDefinition,
    get_autonomous_codex_configuration,
    select_skill,
)
from amoscloud_ai.codex_system_bundle import codex_system_manifest


_COMMAND_SKILLS = {
    "fix": "engineering",
    "review": "engineering",
    "verify": "engineering",
    "inspect": None,
}


def _tool_index(config: AutonomousCodexConfiguration) -> dict[str, ToolDefinition]:
    return {tool.name: tool for tool in config.tools if tool.enabled}


def _selected_tools(skill: SkillDefinition, config: AutonomousCodexConfiguration) -> list[dict[str, Any]]:
    tools = _tool_index(config)
    selected: list[dict[str, Any]] = []
    for name in skill.tools:
        tool = tools.get(name)
        if not tool:
            continue
        selected.append(
            {
                "name": tool.name,
                "category": tool.category,
                "write_capable": tool.write_capable,
                "approval_required": tool.approval_required,
            }
        )
    return selected


def prepare_codex_capabilities(command: str, objective: str) -> dict[str, Any]:
    """Return a safe, secret-free Codex capability plan for GitHub Bot context.

    This does not call an external model and does not grant tool authority. It only
    exposes the repository's existing skill, tool, limit, and verification contracts
    so the Bot can make a better plan before the existing approval and execution gates.
    """

    config = get_autonomous_codex_configuration()
    requested_skill = _COMMAND_SKILLS.get(command)
    skill = select_skill(objective, requested=requested_skill)
    manifest, metadata = codex_system_manifest()
    tools = _selected_tools(skill, config)
    write_tools = [item["name"] for item in tools if item["write_capable"]]
    approval_tools = [item["name"] for item in tools if item["approval_required"]]

    return {
        "configuration_version": config.version,
        "skill": {
            "name": skill.name,
            "title": skill.title,
            "mission": skill.mission,
            "phases": list(skill.phases),
            "default_write_policy": skill.default_write_policy,
        },
        "tools": tools,
        "write_tools": write_tools,
        "approval_tools": approval_tools,
        "limits": {
            "max_iterations": config.max_iterations,
            "max_changed_files": config.max_changed_files,
            "max_tool_calls": config.max_tool_calls,
        },
        "verification": {
            "planning_required": config.planning_required,
            "verification_required": config.verification_required,
            "rollback_on_failed_verification": config.rollback_on_failed_verification,
            "required_checks": list(manifest["verification"]["required_checks"]),
            "completion_requires_pass": bool(manifest["verification"]["completion_requires_pass"]),
        },
        "workspace": dict(manifest["workspace"]),
        "agent_loop": list(manifest["agent_loop"]["stages"]),
        "bundle": {
            "schema": metadata["schema"],
            "contains_secrets": metadata["contains_secrets"],
        },
        "external_model_execution": False,
        "authority_note": "Capability context never bypasses privacy, approval, verification, or publication gates.",
    }

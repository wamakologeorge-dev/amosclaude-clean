"""Canonical prompts for the Amosclaud Autonomous engineering agent.

This module contains instruction text and deterministic prompt helpers only.
It has no network, filesystem, model-loading, or execution side effects, which
keeps imports safe during test collection and command-line validation.
"""

from __future__ import annotations

from collections.abc import Iterable

from amoscloud_ai.agent.assistant_system_template import (
    SYSTEM_PROMPT as ASSISTANT_SYSTEM_PROMPT,
)

SYSTEM_PROMPT = (
    ASSISTANT_SYSTEM_PROMPT
    + "\n\nEngineering execution contract:\n"
    "1. Define observable success criteria before changing the repository.\n"
    "2. Inspect only evidence relevant to the requested outcome.\n"
    "3. Keep questions and guidance separate from authorized execution.\n"
    "4. Never claim a file, issue, branch, commit, pull request, test, deployment, "
    "or repair exists unless a tool or runtime confirms it.\n"
    "5. Work only inside the designated workspace and respect repository boundaries.\n"
    "6. Prefer the smallest safe change that addresses the verified root cause.\n"
    "7. Preserve authentication, ownership, secrets, user data, and security controls.\n"
    "8. Do not delete, reset, overwrite, deploy, merge, or perform another high-impact "
    "action without explicit authorization and a governed tool path.\n"
    "9. After each change, run the most focused relevant verification first.\n"
    "10. When verification fails, report the failing check, affected location, "
    "evidence, attempted repair, and next safe action.\n"
    "11. Specialized models, doctors, workers, and services are tools. Amosclaud "
    "Autonomous remains the single coordinator and final reporter.\n"
    "12. Explain the result inside Amosclaud and include exact result locations."
)

CODING_PROMPT = """Implement the smallest maintainable change that satisfies
the verified objective. Follow existing project conventions, preserve public
contracts, handle errors explicitly, avoid secrets in source code, and add or
update focused tests. Do not report completion until verification evidence
exists."""

DEBUGGING_PROMPT = """Reproduce or identify the exact failure, trace it to the
first verified root cause, distinguish primary failures from secondary
warnings, apply a bounded repair, and rerun the failing check. Report anything
that remains unresolved."""

TESTING_PROMPT = """Select tests that directly prove the requested behavior
and its important safety boundaries. Report command, exit status, concise
output, skipped coverage, and whether the evidence supports the claimed
result."""


def build_task_prompt(
    objective: str,
    evidence: Iterable[str] = (),
    *,
    mode: str = "inspect",
    success_criteria: Iterable[str] = (),
) -> str:
    """Create a deterministic user prompt for the model gateway."""

    clean_objective = objective.strip()
    if not clean_objective:
        raise ValueError("objective must not be empty")

    evidence_lines = [item.strip() for item in evidence if item and item.strip()]
    criteria_lines = [
        item.strip()
        for item in success_criteria
        if item and item.strip()
    ]

    sections = [
        f"Mode: {mode.strip() or 'inspect'}",
        f"Objective: {clean_objective}",
        "Verified evidence:",
        *(f"- {item}" for item in evidence_lines),
    ]
    if not evidence_lines:
        sections.append("- No verified evidence supplied yet.")

    sections.append("Success criteria:")
    if criteria_lines:
        sections.extend(f"- {item}" for item in criteria_lines)
    else:
        sections.append("- Define observable criteria before claiming completion.")

    sections.append(
        "Return a direct answer for conversation or a bounded plan and "
        "evidence-based result for execution. Do not invent completed actions."
    )
    return "\n".join(sections)


__all__ = [
    "SYSTEM_PROMPT",
    "CODING_PROMPT",
    "DEBUGGING_PROMPT",
    "TESTING_PROMPT",
    "build_task_prompt",
]

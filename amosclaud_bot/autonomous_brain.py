"""GitHub-native brain context for the Amosclaud Actions bot.

This module is deliberately an adapter, not another agent runtime. It connects the
existing AgentMemory, Autonomous Learning Academy, Universal Curriculum, and agent
roles to the repository-local GitHub bot. The website and external deployment
services are not required.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from amoscloud_ai.agent_memory import AgentMemory
from amoscloud_ai.autonomous_learning_academy import AGENT_ROLES, AutonomousLearningAcademy
from src.foundation.curriculum import UniversalCurriculum

COMMAND_AGENT_ROLES: dict[str, tuple[int, ...]] = {
    "inspect": (1, 2, 3),
    "review": (2, 5),
    "verify": (2, 5),
    "fix": (2, 3, 4, 5),
}

SUCCESS_STATES = {"success", "pass", "passed", "verified", "healthy", "completed"}
FAILURE_STATES = {"failure", "failed", "error", "blocked", "critical", "rolled_back"}


def _bounded_level(value: str | int | None) -> int:
    try:
        level = int(value or 1)
    except (TypeError, ValueError):
        level = 1
    return max(1, min(level, UniversalCurriculum.max_level))


class GitHubAutonomousBrain:
    """Prepare and record evidence-aware context for one GitHub Bot task."""

    def __init__(self, workspace: Path, repository: str) -> None:
        self.workspace = workspace.resolve()
        self.repository = repository.strip().lower()
        configured = os.getenv("AMOSCLAUD_BOT_BRAIN_HOME", "").strip()
        if configured:
            brain_root = Path(configured).expanduser().resolve()
        elif (self.workspace / ".git").exists():
            brain_root = self.workspace / ".git" / "amosclaud-brain"
        else:
            brain_root = self.workspace / ".amosclaud" / "bot-brain"
        brain_root.mkdir(parents=True, exist_ok=True)
        self.brain_root = brain_root
        self.memory = AgentMemory(brain_root / "memory")
        self.academy = AutonomousLearningAcademy(brain_root / "autonomous-academy.db")
        self.curriculum = UniversalCurriculum()

    @property
    def current_level(self) -> int:
        return _bounded_level(os.getenv("AMOSCLAUD_AUTONOMOUS_LEVEL", "1"))

    def prepare(self, command: str, objective: str) -> dict[str, Any]:
        """Return compact, verified guidance before the bot invokes the kernel."""
        agent_ids = COMMAND_AGENT_ROLES.get(command, (1, 2, 3, 5))
        successful = self.memory.recall(
            objective,
            limit=5,
            project=self.repository,
            include_failures=False,
        )
        all_matches = self.memory.recall(
            objective,
            limit=8,
            project=self.repository,
            include_failures=True,
        )
        failed = [item for item in all_matches if item.get("outcome") == "failure"][:3]

        lessons: list[dict[str, Any]] = []
        seen_lessons: set[int] = set()
        for agent_id in agent_ids:
            for lesson in self.academy.lesson_for_issue(objective, agent_id=agent_id, limit=3):
                lesson_id = int(lesson["id"])
                if lesson_id not in seen_lessons:
                    lessons.append(lesson)
                    seen_lessons.add(lesson_id)

        level = self.current_level
        current_lesson = self.curriculum.lesson(level).to_dict()
        next_lesson = self.curriculum.next_lesson(level)
        return {
            "source": "amosclaud-github-actions-bot",
            "repository": self.repository,
            "agent_roles": [
                {"id": agent_id, "role": AGENT_ROLES[agent_id]} for agent_id in agent_ids
            ],
            "current_level": level,
            "current_curriculum": current_lesson,
            "next_curriculum": next_lesson,
            "proven_memories": [self._memory_guidance(item) for item in successful],
            "failed_attempts_to_avoid": [self._memory_guidance(item) for item in failed],
            "approved_lessons": [self._lesson_guidance(item) for item in lessons[:5]],
            "rules": [
                "Use memory and lessons as guidance, never as proof for the current task.",
                "Re-check the current repository and GitHub Actions evidence independently.",
                "Do not let memory, curriculum, or lessons grant write authority.",
                "Do not report success without current verification evidence.",
            ],
        }

    def observe(
        self,
        command: str,
        objective: str,
        result: dict[str, Any],
        *,
        source_run_id: str = "",
    ) -> dict[str, Any]:
        """Record the task outcome without promoting unverified output to a lesson."""
        status = str(result.get("status") or "unknown").strip().lower()
        evidence = [str(item) for item in (result.get("evidence") or []) if str(item).strip()]
        changed_files = [
            str(item) for item in (result.get("changed_files") or []) if str(item).strip()
        ]
        outcome = self._outcome(status, evidence)
        confidence = {
            "success": 0.85,
            "failure": 0.75,
            "partial": 0.55,
            "unknown": 0.35,
        }[outcome]
        content = self._outcome_content(
            command=command,
            objective=objective,
            status=status,
            evidence=evidence,
            changed_files=changed_files,
            error=str(result.get("error") or ""),
        )
        return self.memory.remember(
            kind=f"github-bot-{command}",
            title=f"{command.capitalize()} outcome: {objective[:180]}",
            content=content,
            tags=["github-actions", "amosclaud-bot", command, outcome],
            importance=0.9 if command == "fix" else 0.7,
            source_run_id=source_run_id or None,
            project=self.repository,
            confidence=confidence,
            outcome=outcome,
        )

    @staticmethod
    def _outcome(status: str, evidence: list[str]) -> str:
        if status in SUCCESS_STATES:
            return "success" if evidence else "partial"
        if status in FAILURE_STATES:
            return "failure"
        if evidence:
            return "partial"
        return "unknown"

    @staticmethod
    def _outcome_content(
        *,
        command: str,
        objective: str,
        status: str,
        evidence: list[str],
        changed_files: list[str],
        error: str,
    ) -> str:
        lines = [
            f"Command: {command}",
            f"Objective: {objective}",
            f"Runtime status: {status or 'unknown'}",
        ]
        if changed_files:
            lines.append("Changed files: " + ", ".join(changed_files[:20]))
        if evidence:
            lines.append("Evidence: " + " | ".join(evidence[:12]))
        if error:
            lines.append("Error: " + error[:1000])
        return "\n".join(lines)

    @staticmethod
    def _memory_guidance(memory: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": memory["id"],
            "kind": memory["kind"],
            "title": memory["title"],
            "content": memory["content"],
            "outcome": memory.get("outcome", "unknown"),
            "confidence": memory.get("confidence", 0.5),
            "importance": memory.get("importance", 0.5),
        }

    @staticmethod
    def _lesson_guidance(lesson: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": lesson["id"],
            "title": lesson["title"],
            "problem_signature": lesson["problem_signature"],
            "root_cause": lesson["root_cause"],
            "resolution": lesson["resolution"],
            "verification": lesson["verification"],
            "source_reference": lesson["source_reference"],
            "match_score": lesson.get("match_score", 0),
        }

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from amoscloud_ai.amo_lang import AmoRuntime, parse_amo
from amoscloud_ai.core.workspace import WorkspaceEngine


class AgentCommandError(RuntimeError):
    pass


@dataclass
class AgentStep:
    action: str
    description: str
    arguments: dict[str, Any] = field(default_factory=dict)
    requires_confirmation: bool = False


@dataclass
class AgentPlan:
    instruction: str
    steps: list[AgentStep]

    def to_dict(self) -> dict[str, Any]:
        return {
            "instruction": self.instruction,
            "steps": [
                {
                    "action": step.action,
                    "description": step.description,
                    "arguments": step.arguments,
                    "requires_confirmation": step.requires_confirmation,
                }
                for step in self.steps
            ],
        }


class AmosclaudCommandAgent:
    """Translate owner instructions into constrained, auditable local actions.

    Version 1 intentionally supports only workspace-safe operations. Git commits,
    pull requests, design generation, and repository publishing are represented in
    plans but remain blocked until a dedicated approved adapter is connected.
    """

    def __init__(self, workspace: WorkspaceEngine | None = None):
        self.workspace = workspace or WorkspaceEngine()
        self.amo = AmoRuntime(self.workspace)

    def plan(self, instruction: str) -> AgentPlan:
        text = instruction.strip()
        if not text:
            raise AgentCommandError("Instruction is required")

        steps: list[AgentStep] = []
        lower = text.lower()

        write_match = re.search(
            r"(?:write|create|replace)\s+(?:the\s+)?file\s+[`\"']?([^`\"']+?)[`\"']?\s+(?:with|to contain|containing)\s+(.+)$",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if write_match:
            steps.append(
                AgentStep(
                    "workspace.write",
                    f"Write {write_match.group(1).strip()}",
                    {"path": write_match.group(1).strip(), "content": write_match.group(2).strip()},
                )
            )

        read_match = re.search(
            r"(?:read|open|inspect)\s+(?:the\s+)?file\s+[`\"']?([^`\"']+)[`\"']?",
            text,
            re.IGNORECASE,
        )
        if read_match and write_match is None:
            steps.append(
                AgentStep(
                    "workspace.read",
                    f"Read {read_match.group(1).strip()}",
                    {"path": read_match.group(1).strip()},
                )
            )

        project_match = re.search(
            r"create\s+(?:a\s+)?project\s+(?:called|named)\s+[`\"']?([^`\"']+)[`\"']?",
            text,
            re.IGNORECASE,
        )
        if project_match:
            name = project_match.group(1).strip()
            steps.append(AgentStep("project.create", f"Create project {name}", {"name": name}))

        repo_match = re.search(
            r"create\s+(?:a\s+)?repository\s+(?:called|named)\s+[`\"']?([^`\"']+)[`\"']?",
            text,
            re.IGNORECASE,
        )
        if repo_match:
            name = repo_match.group(1).strip()
            steps.append(
                AgentStep(
                    "repository.create",
                    f"Create local repository {name}",
                    {"name": name},
                    requires_confirmation=True,
                )
            )

        if "run tests" in lower or "test this" in lower or "test the project" in lower:
            steps.append(AgentStep("tests.run", "Run approved project tests", requires_confirmation=True))

        if "graphic design" in lower or "design a" in lower or "create an image" in lower:
            steps.append(
                AgentStep(
                    "design.create",
                    "Create a design asset through an approved design adapter",
                    {"prompt": text},
                    requires_confirmation=True,
                )
            )

        if "commit" in lower:
            steps.append(AgentStep("git.commit", "Commit completed changes", requires_confirmation=True))

        if "pull request" in lower or re.search(r"\bpr\b", lower):
            steps.append(AgentStep("github.pull_request", "Open a pull request", requires_confirmation=True))

        if any(term in lower for term in ("delete ", "erase ", "wipe ", "remove repository")):
            steps.append(AgentStep("destructive.request", "Perform a destructive action", requires_confirmation=True))

        if not steps:
            steps.append(
                AgentStep(
                    "agent.respond",
                    "Interpret the instruction and request clarification before acting",
                    {"prompt": text},
                )
            )

        return AgentPlan(text, steps)

    def execute(self, plan: AgentPlan, *, confirmed_actions: set[str] | None = None) -> dict[str, Any]:
        confirmed_actions = confirmed_actions or set()
        completed: list[dict[str, Any]] = []
        blocked: list[dict[str, Any]] = []

        for step in plan.steps:
            if step.requires_confirmation and step.action not in confirmed_actions:
                blocked.append({"action": step.action, "reason": "confirmation_required"})
                continue

            try:
                completed.append(
                    {
                        "action": step.action,
                        "status": "completed",
                        "result": self._execute_step(step),
                    }
                )
            except NotImplementedError as exc:
                blocked.append({"action": step.action, "reason": str(exc)})
            except Exception as exc:
                completed.append(
                    {
                        "action": step.action,
                        "status": "failed",
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )

        self.workspace.append_activity(
            {
                "action": "command-agent.executed",
                "instruction": plan.instruction,
                "completed": len(completed),
                "blocked": len(blocked),
            }
        )
        return {
            "instruction": plan.instruction,
            "completed": completed,
            "blocked": blocked,
            "status": "completed" if not blocked and all(item["status"] == "completed" for item in completed) else "partial",
        }

    def _execute_step(self, step: AgentStep) -> Any:
        if step.action == "workspace.write":
            path = self.workspace._safe_path(step.arguments["path"])
            content = step.arguments["content"]
            self.workspace._atomic_write_text(path, content)
            return {
                "path": path.relative_to(self.workspace.root).as_posix(),
                "bytes": len(content.encode("utf-8")),
            }

        if step.action == "workspace.read":
            item = self.workspace.read_item(step.arguments["path"])
            return {"path": item["path"], "content": item["content"]}

        if step.action == "project.create":
            return self.workspace.create_project(step.arguments["name"], "Created by the Amosclaud command agent")

        if step.action == "agent.respond":
            return {
                "message": "I need a more specific instruction before changing files.",
                "instruction": step.arguments["prompt"],
            }

        if step.action in {
            "repository.create",
            "tests.run",
            "design.create",
            "git.commit",
            "github.pull_request",
            "destructive.request",
        }:
            raise NotImplementedError("approved adapter not connected yet")

        raise AgentCommandError(f"Unsupported action: {step.action}")

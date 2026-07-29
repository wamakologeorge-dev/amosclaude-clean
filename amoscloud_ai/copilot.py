"""Repository-aware Amosclaud Copilot coordination and compatibility replies.

The original module only supplied display strings for pipeline and deployment
status.  Those compatibility functions remain stable, while the new Copilot
layer routes coding work to the most appropriate Amosclaud agent and prepares a
bounded handoff to the existing governed autonomous pipeline.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import PurePosixPath
from typing import Iterable

from amoscloud_ai.models import DeploymentStatus, PipelineStatus

# Backward-compatible pipeline identity. Existing pipeline and deployment
# clients depend on these values, so the coding assistant uses separate public
# identity constants below.
PIPELINE_SERVER_NAME = "Amosclaud Autonomous Server"
COPILOT_OWNER = "Amosclaud"
COPILOT_ROLE = "autonomous build, deployment, and monitoring server"
COPILOT_HOME = "amosclaud.com"
COPILOT_PIPELINE = "Amosclaud autonomous pipeline"

COPILOT_NAME = "Amosclaud Copilot"
COPILOT_ID = "amosclaud-copilot"
COPILOT_VERSION = "1.0"
COPILOT_ASSISTANT_ROLE = "repository-aware coding assistant and multi-agent coordinator"
COPILOT_MISSION = (
    "Understand repository code, explain and propose changes, select the right "
    "Amosclaud agent, and delegate authorized work to the governed Autonomous pipeline."
)
COPILOT_SCOPE = [
    "repository code and documentation",
    "Amosclaud agent coordination",
    COPILOT_PIPELINE,
]
COPILOT_DIRECTIVES = [
    "Use repository context before proposing code changes.",
    "Choose one primary agent and only the supporting agents needed for the task.",
    "Send write-capable work through the existing governed Autonomous pipeline.",
    "Preserve human approval for sensitive files, merges, deployments, and secrets.",
    "Report the selected agent, workflow, verification plan, and resulting evidence.",
]


@dataclass(frozen=True, slots=True)
class CopilotAgent:
    """One agent that Amosclaud Copilot may coordinate."""

    name: str
    title: str
    mission: str
    capabilities: tuple[str, ...]
    modes: tuple[str, ...]
    keywords: tuple[str, ...]

    def public_dict(self) -> dict[str, object]:
        data = asdict(self)
        data.pop("keywords", None)
        return data


AGENTS: tuple[CopilotAgent, ...] = (
    CopilotAgent(
        name="amosclaud-security",
        title="Amosclaud Security Agent",
        mission=(
            "Review authentication, authorization, secrets, dependencies, and "
            "security-sensitive code paths."
        ),
        capabilities=("security-review", "auth-review", "secret-safety", "dependency-risk"),
        modes=("autonomous-check", "fix"),
        keywords=(
            "security",
            "vulnerability",
            "authentication",
            "authorization",
            "permission",
            "secret",
            "token",
            "credential",
            "xss",
            "csrf",
            "injection",
        ),
    ),
    CopilotAgent(
        name="amosclaud-fixer",
        title="Amosclaud Fixer",
        mission="Diagnose verified failures and apply the smallest safe repair.",
        capabilities=("bug-fix", "failure-diagnosis", "regression-repair", "verification"),
        modes=("fix", "autonomous-check"),
        keywords=(
            "fix",
            "repair",
            "bug",
            "error",
            "failure",
            "failing",
            "broken",
            "exception",
            "regression",
            "crash",
        ),
    ),
    CopilotAgent(
        name="amosclaud-action",
        title="Amosclaud Action Agent",
        mission=(
            "Create and verify tests, CI workflows, repository actions, and "
            "repeatable automation."
        ),
        capabilities=("tests", "github-actions", "ci", "automation", "pipeline-verification"),
        modes=("build", "fix", "autonomous-check"),
        keywords=(
            "test",
            "tests",
            "workflow",
            "github action",
            "ci",
            "pipeline",
            "automation",
            "automate",
            "check",
        ),
    ),
    CopilotAgent(
        name="amosclaud-clean",
        title="Amosclaud Clean Agent",
        mission="Improve code quality without changing intended behavior.",
        capabilities=("lint", "format", "cleanup", "deduplication", "maintainability"),
        modes=("fix", "autonomous-check"),
        keywords=(
            "clean",
            "lint",
            "format",
            "style",
            "duplicate",
            "dead code",
            "quality",
            "maintainability",
        ),
    ),
    CopilotAgent(
        name="amosclaud-codex-agent",
        title="Amosclaud Codex Agent",
        mission="Understand code and implement repository-aware software changes.",
        capabilities=(
            "code-generation",
            "code-explanation",
            "refactoring",
            "implementation",
            "review",
        ),
        modes=("build", "fix", "autonomous-check"),
        keywords=(
            "code",
            "implement",
            "function",
            "class",
            "api",
            "refactor",
            "complete",
            "autocomplete",
            "explain code",
            "review code",
            "feature",
        ),
    ),
    CopilotAgent(
        name="amosclaud-autonomous",
        title="Amosclaud Autonomous Agent",
        mission="Coordinate full repository work from inspection through verified delivery.",
        capabilities=(
            "planning",
            "repository-execution",
            "deployment",
            "monitoring",
            "evidence-reporting",
        ),
        modes=("autonomous-check", "build", "fix", "deploy", "monitor"),
        keywords=(
            "build",
            "create",
            "repository",
            "project",
            "deploy",
            "release",
            "monitor",
            "end to end",
            "full implementation",
        ),
    ),
    CopilotAgent(
        name="amosclaud-ai-agent",
        title="Amosclaud AI Agent",
        mission=(
            "Answer technical questions and turn developer intent into a clear "
            "engineering objective."
        ),
        capabilities=("technical-chat", "requirements", "explanation", "planning"),
        modes=("autonomous-check",),
        keywords=(
            "explain",
            "why",
            "how",
            "question",
            "help",
            "plan",
            "compare",
            "understand",
        ),
    ),
)

_AGENT_BY_NAME = {agent.name: agent for agent in AGENTS}
_AGENT_ALIASES = {
    "security": "amosclaud-security",
    "fixer": "amosclaud-fixer",
    "action": "amosclaud-action",
    "clean": "amosclaud-clean",
    "codex": "amosclaud-codex-agent",
    "autonomous": "amosclaud-autonomous",
    "ai": "amosclaud-ai-agent",
    "ai-agent": "amosclaud-ai-agent",
}


def available_agents() -> list[dict[str, object]]:
    """Return the safe public agent registry used by Copilot clients."""

    return [agent.public_dict() for agent in AGENTS]


def _normalise(value: str | None) -> str:
    return " ".join((value or "").strip().lower().replace("_", "-").split())


def _resolve_requested_agent(requested_agent: str | None) -> CopilotAgent | None:
    requested = _normalise(requested_agent)
    if not requested:
        return None
    requested = _AGENT_ALIASES.get(requested, requested)
    try:
        return _AGENT_BY_NAME[requested]
    except KeyError as exc:
        choices = ", ".join(sorted(_AGENT_BY_NAME))
        raise ValueError(f"Unknown Amosclaud agent: {requested}. Choose one of: {choices}") from exc


def _score(agent: CopilotAgent, text: str) -> int:
    score = 0
    words = set(text.replace("/", " ").replace("-", " ").split())
    for keyword in agent.keywords:
        if " " in keyword:
            if keyword in text:
                score += 4
        elif keyword in words:
            score += 2
        elif keyword in text:
            score += 1
    return score


def _unique_agents(agents: Iterable[CopilotAgent], *, exclude: str) -> list[CopilotAgent]:
    selected: list[CopilotAgent] = []
    seen = {exclude}
    for agent in agents:
        if agent.name in seen:
            continue
        selected.append(agent)
        seen.add(agent.name)
    return selected


def select_agents(
    task: str, requested_agent: str | None = None
) -> tuple[CopilotAgent, list[CopilotAgent]]:
    """Select one primary agent and a small supporting team deterministically."""

    objective = task.strip()
    if not objective:
        raise ValueError("Copilot task must not be blank")

    explicit = _resolve_requested_agent(requested_agent)
    if explicit:
        primary = explicit
    else:
        text = _normalise(objective)
        ranked = sorted(
            ((_score(agent, text), index, agent) for index, agent in enumerate(AGENTS)),
            key=lambda item: (-item[0], item[1]),
        )
        primary = ranked[0][2] if ranked[0][0] > 0 else _AGENT_BY_NAME["amosclaud-codex-agent"]

    text = _normalise(objective)
    candidates: list[CopilotAgent] = []
    if primary.name != "amosclaud-autonomous":
        candidates.append(_AGENT_BY_NAME["amosclaud-autonomous"])
    if primary.name != "amosclaud-action" and any(
        term in text for term in ("test", "ci", "workflow", "verify")
    ):
        candidates.append(_AGENT_BY_NAME["amosclaud-action"])
    if primary.name != "amosclaud-security" and any(
        term in text for term in ("auth", "permission", "secret", "security", "token", "credential")
    ):
        candidates.append(_AGENT_BY_NAME["amosclaud-security"])
    if primary.name != "amosclaud-clean" and any(
        term in text for term in ("lint", "format", "clean", "quality", "refactor")
    ):
        candidates.append(_AGENT_BY_NAME["amosclaud-clean"])
    if primary.name not in {"amosclaud-codex-agent", "amosclaud-ai-agent"}:
        candidates.append(_AGENT_BY_NAME["amosclaud-codex-agent"])

    return primary, _unique_agents(candidates, exclude=primary.name)[:3]


def execution_mode(task: str, primary: CopilotAgent) -> str:
    """Translate developer intent into an existing Autonomous runtime mode."""

    text = _normalise(task)
    if any(term in text for term in ("deploy", "release", "publish to production")):
        mode = "deploy"
    elif any(term in text for term in ("monitor", "watch status", "observe")):
        mode = "monitor"
    elif any(
        term in text
        for term in ("fix", "repair", "bug", "error", "failing", "broken", "regression")
    ):
        mode = "fix"
    elif any(term in text for term in ("explain", "review", "inspect", "why", "how", "question")):
        mode = "autonomous-check"
    else:
        mode = "build"
    return mode if mode in primary.modes else primary.modes[0]


def normalise_repository_path(path: str | None) -> str | None:
    """Validate an optional repository-relative path without touching the filesystem."""

    raw = (path or "").strip().replace("\\", "/")
    if not raw:
        return None
    candidate = PurePosixPath(raw)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError("file_path must stay inside the repository")
    return candidate.as_posix()


def _bounded(value: str | None, limit: int) -> str | None:
    text = (value or "").strip()
    return text[:limit] if text else None


def build_copilot_plan(
    task: str,
    *,
    requested_agent: str | None = None,
    repository: str | None = None,
    branch: str = "main",
    file_path: str | None = None,
    selection: str | None = None,
    language: str | None = None,
    source: str | None = None,
) -> dict[str, object]:
    """Build a transparent Copilot plan and Autonomous handoff payload."""

    objective = task.strip()
    if not objective:
        raise ValueError("Copilot task must not be blank")

    primary, supporting = select_agents(objective, requested_agent)
    mode = execution_mode(objective, primary)
    safe_path = normalise_repository_path(file_path)
    safe_branch = (branch or "main").strip()[:255] or "main"
    context = {
        "repository": _bounded(repository, 255),
        "branch": safe_branch,
        "file_path": safe_path,
        "selection": _bounded(selection, 16000),
        "language": _bounded(language, 64),
        "source": _bounded(source, 128) or "amosclaud-copilot",
    }
    context = {key: value for key, value in context.items() if value is not None}

    metadata = {
        "source": "amosclaud-copilot",
        "copilot_version": COPILOT_VERSION,
        "copilot_primary_agent": primary.name,
        "copilot_supporting_agents": [agent.name for agent in supporting],
        "copilot_context": context,
        "agent_workflow": True,
        "phases": ["understand", "context", "route", "act", "verify", "review", "report"],
    }
    handoff_objective = f"{objective}\n\nAmosclaud Copilot primary agent: {primary.name}."

    return {
        "copilot": {
            "id": COPILOT_ID,
            "name": COPILOT_NAME,
            "version": COPILOT_VERSION,
            "role": COPILOT_ASSISTANT_ROLE,
        },
        "task": objective,
        "execution_mode": mode,
        "primary_agent": primary.public_dict(),
        "supporting_agents": [agent.public_dict() for agent in supporting],
        "workflow": [
            "understand developer intent",
            "collect bounded repository context",
            f"delegate to {primary.name}",
            "run authorized tools through the governed pipeline",
            "verify tests and review the diff",
            "report evidence and remaining risks",
        ],
        "context": context,
        "handoff": {
            "route": "/api/v1/agent/run",
            "payload": {
                "mode": mode,
                "objective": handoff_objective,
                "branch": safe_branch,
                "metadata": metadata,
            },
        },
        "safety": {
            "direct_main_write": False,
            "human_approval_for_sensitive_changes": True,
            "verification_required": True,
            "secrets_in_response": False,
        },
    }


PIPELINE_REPLIES = {
    PipelineStatus.PENDING: (
        f"{PIPELINE_SERVER_NAME}: autonomous pipeline run queued for {COPILOT_HOME}."
    ),
    PipelineStatus.RUNNING: (
        f"{PIPELINE_SERVER_NAME}: autonomous pipeline run is active in the {COPILOT_PIPELINE}."
    ),
    PipelineStatus.SUCCESS: (
        f"{PIPELINE_SERVER_NAME}: The {COPILOT_PIPELINE} finished successfully for {COPILOT_HOME}."
    ),
    PipelineStatus.FAILED: (
        f"{PIPELINE_SERVER_NAME}: The {COPILOT_PIPELINE} failed. "
        "Check the pipeline logs for the failing step."
    ),
    PipelineStatus.CANCELLED: (
        f"{PIPELINE_SERVER_NAME}: The {COPILOT_PIPELINE} build was cancelled."
    ),
}

DEPLOYMENT_REPLIES = {
    DeploymentStatus.PENDING: (
        f"{PIPELINE_SERVER_NAME}: deployment queued for {COPILOT_HOME} in the {COPILOT_PIPELINE}."
    ),
    DeploymentStatus.IN_PROGRESS: (
        f"{PIPELINE_SERVER_NAME}: autonomous deployment is active through the {COPILOT_PIPELINE}."
    ),
    DeploymentStatus.COMPLETED: (
        f"{PIPELINE_SERVER_NAME}: Deployment completed successfully for {COPILOT_HOME}."
    ),
    DeploymentStatus.FAILED: (
        f"{PIPELINE_SERVER_NAME}: Deployment failed in the {COPILOT_PIPELINE}. "
        "Check the deployment logs for details."
    ),
    DeploymentStatus.ROLLED_BACK: (
        f"{PIPELINE_SERVER_NAME}: Deployment was rolled back successfully."
    ),
}


def pipeline_reply(status: PipelineStatus) -> str:
    return PIPELINE_REPLIES[status]


def deployment_reply(status: DeploymentStatus) -> str:
    return DEPLOYMENT_REPLIES[status]


def copilot_profile() -> dict[str, object]:
    return {
        "id": COPILOT_ID,
        "name": COPILOT_NAME,
        "version": COPILOT_VERSION,
        "owner": COPILOT_OWNER,
        "role": COPILOT_ASSISTANT_ROLE,
        "mission": COPILOT_MISSION,
        "home": COPILOT_HOME,
        "pipeline": COPILOT_PIPELINE,
        "scope": COPILOT_SCOPE,
        "directives": COPILOT_DIRECTIVES,
        "agents": available_agents(),
        "endpoints": {
            "profile": "/api/v1/copilot",
            "agents": "/api/v1/copilot/agents",
            "plan": "/api/v1/copilot/plan",
            "run": "/api/v1/copilot/run",
        },
    }

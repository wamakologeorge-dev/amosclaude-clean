"""Central operator contract and API for Amosclaud-bot.

Every public entry point translates user intent through this module before work
is submitted to the global task router. Specialized agents remain internal
workers; Amosclaud-bot is the single operator visible to users.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from fastapi import Cookie, Header
from pydantic import BaseModel, Field

OperatorMode = Literal["ask", "build", "fix", "test", "review", "deploy", "monitor"]


@dataclass(frozen=True, slots=True)
class OperatorRequest:
    """A normalized request accepted by the Amosclaud-bot operator."""

    objective: str
    repository: str | None = None
    mode: OperatorMode | None = None
    require_approval: bool = True
    source: str = "amosclaud-platform"
    conversation_id: str | None = None
    metadata: dict[str, Any] | None = None


class OperatorSubmit(BaseModel):
    """HTTP request accepted from the platform, CLI, SDK, or GitHub adapter."""

    objective: str = Field(min_length=3, max_length=20_000)
    repository: str | None = Field(default=None, max_length=300)
    mode: OperatorMode | None = None
    require_approval: bool = True
    source: str = Field(default="amosclaud-platform", max_length=100)
    conversation_id: str | None = Field(default=None, max_length=200)
    metadata: dict[str, Any] = Field(default_factory=dict)


_MODE_TERMS: tuple[tuple[OperatorMode, tuple[str, ...]], ...] = (
    ("deploy", ("deploy", "release", "publish", "ship")),
    ("fix", ("fix", "repair", "debug", "broken", "error", "failing")),
    ("test", ("test", "verify", "check ci", "run checks")),
    ("review", ("review", "inspect", "audit", "pull request", " pr ")),
    ("monitor", ("monitor", "watch", "alert", "status")),
    ("build", ("build", "create", "implement", "add", "make")),
)


def infer_mode(objective: str) -> OperatorMode:
    """Infer the first safe execution mode from a natural-language objective."""

    normalized = f" {objective.strip().lower()} "
    for mode, terms in _MODE_TERMS:
        if any(term in normalized for term in terms):
            return mode
    return "ask"


def normalize_operator_request(request: OperatorRequest) -> dict[str, Any]:
    """Convert an operator request into the shared global-task payload."""

    objective = request.objective.strip()
    if len(objective) < 3:
        raise ValueError("objective must contain at least 3 characters")

    mode = request.mode or infer_mode(objective)
    metadata = dict(request.metadata or {})
    metadata.update(
        {
            "operator": "Amosclaud-bot",
            "source": request.source,
            "conversation_id": request.conversation_id,
            "single_brain": True,
        }
    )

    return {
        "objective": objective,
        "repository": request.repository,
        "mode": mode,
        "delivery": "report" if mode in {"ask", "monitor"} else "pull_request",
        "execution_target": "github" if request.repository else "cloud",
        "require_approval": request.require_approval,
        "metadata": metadata,
    }


def _register_operator_route() -> None:
    """Attach the operator endpoint to the already-mounted global task router."""

    from amoscloud_ai.api.routes import task_router

    if any(getattr(route, "path", "") == "/operator/requests" for route in task_router.router.routes):
        return

    @task_router.router.post("/operator/requests", status_code=202, tags=["amosclaud-operator"])
    def submit_operator_request(
        body: OperatorSubmit,
        amos_session: str | None = Cookie(default=None),
        authorization: str | None = Header(default=None),
    ) -> dict:
        normalized = normalize_operator_request(
            OperatorRequest(
                objective=body.objective,
                repository=body.repository,
                mode=body.mode,
                require_approval=body.require_approval,
                source=body.source,
                conversation_id=body.conversation_id,
                metadata=body.metadata,
            )
        )
        task = task_router.create_task(
            task_router.TaskCreate.model_validate(normalized),
            amos_session=amos_session,
            authorization=authorization,
        )
        task["operator"] = "Amosclaud-bot"
        return task


_register_operator_route()

# Register persistent projects, issues, and verified result routes on the same
# already-mounted task router. This keeps one database, identity, and task brain.
from amoscloud_ai import project_platform as _project_platform  # noqa: E402,F401

"""Human-centered interaction contracts for Amosclaud Autonomous.

This module controls how autonomous work is explained to a user. It keeps the agent
welcoming and conversational, allows the user to pause or redirect active work, and
produces paced, evidence-aware updates for the mirror panel. It does not execute
repository or deployment actions itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Iterable


class InteractionIntent(StrEnum):
    CONVERSE = "converse"
    PAUSE = "pause"
    RESUME = "resume"
    STOP = "stop"
    ADD_IDEA = "add_idea"
    SHOW_PLAN = "show_plan"
    SHOW_PROGRESS = "show_progress"
    SHOW_HOW = "show_how"
    EXPLORE_ALTERNATIVE = "explore_alternative"


class WorkState(StrEnum):
    PLANNING = "planning"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    EXECUTING = "executing"
    PAUSED = "paused"
    STOPPED = "stopped"
    VERIFYING = "verifying"
    COMPLETED = "completed"


@dataclass(frozen=True, slots=True)
class PlanStep:
    number: int
    title: str
    explanation: str
    status: str = "pending"


@dataclass(frozen=True, slots=True)
class MirrorEvent:
    sequence: int
    phase: str
    title: str
    explanation: str
    evidence: tuple[str, ...] = ()
    user_action_available: tuple[str, ...] = ("pause", "ask", "add idea", "stop")


@dataclass(slots=True)
class InteractionSession:
    objective: str
    state: WorkState = WorkState.PLANNING
    plan: list[PlanStep] = field(default_factory=list)
    ideas: list[str] = field(default_factory=list)
    alternatives: list[str] = field(default_factory=list)
    mirror_events: list[MirrorEvent] = field(default_factory=list)
    next_sequence: int = 1

    def add_mirror_event(
        self,
        *,
        phase: str,
        title: str,
        explanation: str,
        evidence: Iterable[str] = (),
    ) -> MirrorEvent:
        """Add one paced update that the normal-speed mirror panel can display."""

        event = MirrorEvent(
            sequence=self.next_sequence,
            phase=phase,
            title=title,
            explanation=explanation,
            evidence=tuple(evidence),
        )
        self.next_sequence += 1
        self.mirror_events.append(event)
        return event


def recognize_interaction_intent(message: str) -> InteractionIntent:
    """Recognize user control and collaboration requests without authorizing execution."""

    text = " ".join((message or "").strip().lower().split()).rstrip(" ?!.,")

    if text in {"pause", "pause the job", "hold on", "wait", "stop for now"}:
        return InteractionIntent.PAUSE
    if text in {"resume", "continue", "keep going", "proceed", "carry on"}:
        return InteractionIntent.RESUME
    if text in {"stop", "stop the job", "cancel", "cancel the job", "end the task"}:
        return InteractionIntent.STOP
    if any(phrase in text for phrase in ("add this idea", "add an idea", "include this", "change the idea")):
        return InteractionIntent.ADD_IDEA
    if any(phrase in text for phrase in ("show me the plan", "what is the plan", "show every plan")):
        return InteractionIntent.SHOW_PLAN
    if any(phrase in text for phrase in ("show progress", "what are you doing", "where are you now", "mirror panel")):
        return InteractionIntent.SHOW_PROGRESS
    if any(phrase in text for phrase in ("show me how", "demonstrate how", "how is it built", "how are you building")):
        return InteractionIntent.SHOW_HOW
    if any(phrase in text for phrase in ("other path", "another path", "alternative", "different approach")):
        return InteractionIntent.EXPLORE_ALTERNATIVE
    return InteractionIntent.CONVERSE


def apply_interaction(
    session: InteractionSession,
    message: str,
    *,
    idea: str | None = None,
) -> str:
    """Apply a conversational control request and return a human-centered reply."""

    intent = recognize_interaction_intent(message)

    if intent == InteractionIntent.PAUSE:
        session.state = WorkState.PAUSED
        return (
            "Of course. I paused the work at the current safe checkpoint. Nothing else will be "
            "changed until you tell me to continue. You can ask questions or add ideas while it is paused."
        )

    if intent == InteractionIntent.RESUME:
        if session.state == WorkState.STOPPED:
            return "This job was stopped. I can prepare a new plan from the saved objective before restarting."
        session.state = WorkState.EXECUTING
        return (
            f"Welcome back. I am continuing: {session.objective}. I will resume from the next unfinished "
            "step and keep showing the plan, progress, and verification evidence."
        )

    if intent == InteractionIntent.STOP:
        session.state = WorkState.STOPPED
        return (
            "I stopped the job safely. I preserved the objective, plan, completed work, and evidence so "
            "you can review them or start again later without losing the conversation."
        )

    if intent == InteractionIntent.ADD_IDEA:
        captured = (idea or message).strip()
        session.ideas.append(captured)
        return (
            "I added that idea to the project context. Before changing active work, I will show where it "
            "fits in the plan, what it affects, and whether it introduces a safer or better path."
        )

    if intent == InteractionIntent.SHOW_PLAN:
        if not session.plan:
            return "The plan has not been prepared yet. I will create it and explain each step before execution begins."
        rendered = "\n".join(
            f"{step.number}. {step.title} — {step.explanation} [{step.status}]" for step in session.plan
        )
        return f"Here is the current plan:\n{rendered}\nYou can pause, ask about a step, or add an idea at any time."

    if intent == InteractionIntent.SHOW_PROGRESS:
        if not session.mirror_events:
            return "No execution event has been recorded yet. The mirror panel will begin with the approved plan."
        latest = session.mirror_events[-1]
        return (
            f"Current phase: {latest.phase}. {latest.title}. {latest.explanation} "
            "The mirror panel keeps the full timeline and evidence visible at normal reading speed."
        )

    if intent == InteractionIntent.SHOW_HOW:
        return (
            "I will demonstrate the build as a readable sequence: the approved plan, the file or component "
            "being worked on, the reason for each change, the verification result, and the next step. "
            "Fast internal operations will be grouped into understandable mirror-panel updates."
        )

    if intent == InteractionIntent.EXPLORE_ALTERNATIVE:
        return (
            "Yes. I will compare another path before changing direction. I will show the trade-offs, cost, "
            "risk, maintainability, and expected result, then ask whether you want to keep the current plan "
            "or choose the alternative."
        )

    return (
        "I am here as your project partner, not only as a build command. You can talk with me normally, "
        "ask why a choice was made, pause the work, add an idea, request another path, or ask to see exactly "
        "how the project is being built."
    )


def welcoming_message(user_name: str | None = None) -> str:
    """Create a welcoming first message that establishes trust and user control."""

    name = f" {user_name}" if user_name else ""
    return (
        f"Welcome{name}. I am Amosclaud Autonomous, your project partner. We can talk normally while we "
        "plan, build, inspect, fix, test, deploy, or monitor your project. I will show the plan before "
        "execution, explain important decisions, display progress and evidence in the mirror panel, and "
        "let you pause, stop, ask questions, add ideas, or explore another path at any time. What would "
        "you like us to work on today?"
    )

"""Human-centered interaction contracts for Amosclaud Autonomous.

The conversation never ends merely because work is paused, completed, or stopped.
Amosclaud remains on the active project path, preserves context, and always offers the
next meaningful conversational step. This module describes interaction behavior only;
it does not execute repository or deployment actions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Iterable


class InteractionIntent(StrEnum):
    CONVERSE = "converse"
    PAUSE = "pause"
    RESUME = "resume"
    STOP_WORK = "stop_work"
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
    WORK_STOPPED = "work_stopped"
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
    user_action_available: tuple[str, ...] = (
        "pause work",
        "ask a question",
        "add idea",
        "change direction",
        "stop work",
    )


@dataclass(slots=True)
class InteractionSession:
    objective: str
    state: WorkState = WorkState.PLANNING
    conversation_open: bool = True
    current_path: str = "primary"
    next_conversation_step: str = "Understand the user's goal"
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
        """Add one paced update for the normal-speed mirror panel."""

        event = MirrorEvent(
            sequence=self.next_sequence,
            phase=phase,
            title=title,
            explanation=explanation,
            evidence=tuple(evidence),
        )
        self.next_sequence += 1
        self.mirror_events.append(event)
        self.next_conversation_step = f"Discuss or continue after: {title}"
        return event


def recognize_interaction_intent(message: str) -> InteractionIntent:
    """Recognize collaboration requests without silently authorizing execution."""

    text = " ".join((message or "").strip().lower().split()).rstrip(" ?!.,")
    if text in {"pause", "pause the job", "hold on", "wait", "stop for now"}:
        return InteractionIntent.PAUSE
    if text in {"resume", "continue", "keep going", "proceed", "carry on"}:
        return InteractionIntent.RESUME
    if text in {"stop", "stop the job", "cancel", "cancel the job", "stop this work"}:
        return InteractionIntent.STOP_WORK
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
    """Apply a user interaction while keeping the conversation on the project path."""

    session.conversation_open = True
    intent = recognize_interaction_intent(message)

    if intent == InteractionIntent.PAUSE:
        session.state = WorkState.PAUSED
        session.next_conversation_step = "Answer questions, review the plan, or accept a new idea"
        return (
            "Of course. I paused the work at the current safe checkpoint, but our conversation remains "
            "open and connected to this project. Nothing else will be changed until you continue. We can "
            "review the plan, discuss an idea, or explore another path now."
        )

    if intent == InteractionIntent.RESUME:
        session.state = WorkState.EXECUTING
        session.next_conversation_step = "Continue the next unfinished approved step"
        return (
            f"Welcome back. We are still working on: {session.objective}. I am continuing from the next "
            "unfinished approved step. I will keep the conversation, plan, mirror-panel progress, and "
            "verification evidence on the same project path."
        )

    if intent == InteractionIntent.STOP_WORK:
        session.state = WorkState.WORK_STOPPED
        session.next_conversation_step = "Discuss what should change before work resumes"
        return (
            "I stopped the active work safely, not our conversation. The objective, decisions, plan, completed "
            "steps, and evidence are preserved. We can now discuss what should change, choose another path, "
            "or prepare the next approved step together."
        )

    if intent == InteractionIntent.ADD_IDEA:
        captured = (idea or message).strip()
        session.ideas.append(captured)
        session.next_conversation_step = "Show how the new idea affects the current plan"
        return (
            "I added that idea to the active project conversation. I will show where it fits, which plan "
            "steps it affects, and whether it creates a better path before any execution changes."
        )

    if intent == InteractionIntent.SHOW_PLAN:
        if not session.plan:
            session.next_conversation_step = "Create and explain the project plan"
            return (
                "The plan has not been prepared yet. I will build it with you, explain each step, and keep "
                "the conversation focused on the project before execution begins."
            )
        rendered = "\n".join(
            f"{step.number}. {step.title} — {step.explanation} [{step.status}]" for step in session.plan
        )
        return (
            f"Here is the current project path:\n{rendered}\nWe remain on this conversation path. "
            "You can question a step, add an idea, pause work, or ask me to compare another approach."
        )

    if intent == InteractionIntent.SHOW_PROGRESS:
        if not session.mirror_events:
            return (
                "No execution event has been recorded yet. The mirror panel will begin with the agreed plan, "
                "and I will keep explaining what comes next in the conversation."
            )
        latest = session.mirror_events[-1]
        return (
            f"Current phase: {latest.phase}. {latest.title}. {latest.explanation} The mirror panel keeps the "
            "timeline and evidence visible at normal reading speed, while our conversation remains active."
        )

    if intent == InteractionIntent.SHOW_HOW:
        return (
            "I will demonstrate the project as a readable sequence: the agreed plan, the component being "
            "worked on, why each change is needed, the verification result, and the next conversation step. "
            "Fast internal operations will be grouped into understandable mirror-panel updates."
        )

    if intent == InteractionIntent.EXPLORE_ALTERNATIVE:
        session.next_conversation_step = "Compare the current path with an alternative"
        return (
            "Yes. We can explore another path without losing the current one. I will compare trade-offs, "
            "cost, risk, maintainability, and expected result, then keep the conversation on whichever path "
            "you approve."
        )

    session.next_conversation_step = "Respond naturally and connect the reply to the active objective"
    return (
        f"I am following our active objective: {session.objective}. You can speak with me naturally—not only "
        "through build commands. I will connect your question or idea to the right project path, explain what "
        "it changes, and continue with a meaningful next step instead of ending the conversation."
    )


def welcoming_message(user_name: str | None = None) -> str:
    """Create a welcoming first message that establishes continuity and trust."""

    name = f" {user_name}" if user_name else ""
    return (
        f"Welcome{name}. I am Amosclaud Autonomous, your project partner. You can speak with me naturally "
        "while we plan, build, inspect, fix, test, deploy, or monitor your project. I will keep our conversation "
        "on the right project path, show the plan before execution, explain important decisions, and display "
        "progress and evidence in the mirror panel. Pausing or stopping work never ends our conversation. "
        "What would you like us to work on today?"
    )

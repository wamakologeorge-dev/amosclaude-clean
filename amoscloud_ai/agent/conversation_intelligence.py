"""Structured, deterministic conversation analysis for Amosclaud Autonomous.

The analyzer separates education, capability discovery, project guidance, repository
work, and real execution intent before the autonomous runtime is allowed to act.
It also recognizes natural resume commands so a user can continue an unfinished
objective without repeating the conversation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable


class Intent(StrEnum):
    GREETING = "greeting"
    DISCOVER_CAPABILITIES = "discover_capabilities"
    PROJECT_IDEA = "project_idea"
    RESUME = "resume"
    EXPLAIN = "explain"
    SHOW_EXAMPLE = "show_example"
    TEACH = "teach"
    INSPECT = "inspect"
    CHANGE_REPOSITORY = "change_repository"
    TEST = "test"
    DEPLOY = "deploy"
    MONITOR = "monitor"
    GENERAL_QUESTION = "general_question"
    UNKNOWN = "unknown"


class OutputTarget(StrEnum):
    CHAT = "chat"
    REPOSITORY = "repository"
    EXTERNAL_SYSTEM = "external_system"
    NONE = "none"


@dataclass(frozen=True, slots=True)
class ConversationDecision:
    intent: Intent
    output_target: OutputTarget
    execution_requested: bool
    repository_changes_allowed: bool
    explanation_requested: bool
    clarification_required: bool
    confidence: float
    topics: tuple[str, ...]
    contradictions: tuple[str, ...]
    clarification_question: str | None = None
    previous_objective: str | None = None

    def as_metadata(self) -> dict[str, object]:
        return {
            "intent": self.intent.value,
            "output_target": self.output_target.value,
            "execution_requested": self.execution_requested,
            "repository_changes_allowed": self.repository_changes_allowed,
            "explanation_requested": self.explanation_requested,
            "clarification_required": self.clarification_required,
            "confidence": self.confidence,
            "topics": list(self.topics),
            "contradictions": list(self.contradictions),
            "previous_objective": self.previous_objective,
        }


_EXECUTE = {
    "do it",
    "proceed",
    "apply the fix",
    "make the changes",
    "edit the repository",
    "change the repository",
    "commit it",
    "merge it",
    "deploy it",
    "run the tests",
    "build it",
}
_RESUME = {
    "proceed",
    "continue",
    "resume",
    "keep going",
    "carry on",
    "finish it",
    "continue building",
    "continue the work",
    "where were we",
    "proceed where we left off",
    "continue where we left off",
}
_NO_EXECUTE = {
    "do not edit",
    "don't edit",
    "do not change",
    "don't change",
    "do not modify",
    "don't modify",
    "do not deploy",
    "don't deploy",
    "show only",
    "example only",
    "in chat only",
    "just explain",
}
_CAPABILITIES = (
    "what can you do",
    "what can you create",
    "what can you build",
    "what are your capabilities",
    "what do you do",
    "how can you help",
    "show me what you can do",
)
_PROJECT_IDEA = (
    "i have an idea",
    "i have a project idea",
    "help me start a project",
    "i want to build something",
    "i want to create something",
)
_EXPLAIN = ("explain", "what does", "what is", "why does", "walk me through")
_TEACH = ("teach me", "guide me", "show me how", "learn how", "step by step")
_EXAMPLE = ("show me code", "show an example", "give me an example", "sample code", "code example")
_INSPECT = ("inspect", "review", "diagnose", "check the code", "find the problem")
_CHANGE = ("build", "create", "write", "fix", "change", "update", "refactor", "implement", "add", "remove", "delete")
_DEPLOY = ("deploy", "release", "publish to production")
_MONITOR = ("monitor", "watch status", "keep watching")
_TEST = ("run tests", "run the tests", "test the project", "verify the code")
_QUESTION_START = ("who", "what", "when", "where", "why", "how", "can", "could", "would", "is", "are", "do", "does")
_TOPIC_SPLIT = re.compile(r"(?:\.|;|\bbut\b|\balso\b|\bactually\b|\bnow\b)", re.IGNORECASE)


def _contains(text: str, phrases: Iterable[str]) -> bool:
    return any(phrase in text for phrase in phrases)


def _normalized_command(text: str) -> str:
    return text.strip().lower().rstrip(" ?!.,")


def _topics(message: str) -> tuple[str, ...]:
    parts = [" ".join(part.strip().split()) for part in _TOPIC_SPLIT.split(message)]
    useful = [part for part in parts if len(part.split()) >= 2]
    deduplicated: list[str] = []
    for part in useful:
        lowered = part.lower()
        if lowered not in {item.lower() for item in deduplicated}:
            deduplicated.append(part[:240])
    return tuple(deduplicated[:6]) or ((message.strip()[:240],) if message.strip() else ())


def analyze_message(message: str, *, previous_objective: str | None = None) -> ConversationDecision:
    """Classify one user message without authorizing an unrequested real-world action."""

    raw = " ".join((message or "").strip().split())
    text = raw.lower()
    command = _normalized_command(raw)
    topics = _topics(raw)
    if not text:
        return ConversationDecision(
            intent=Intent.UNKNOWN,
            output_target=OutputTarget.NONE,
            execution_requested=False,
            repository_changes_allowed=False,
            explanation_requested=False,
            clarification_required=True,
            confidence=0.0,
            topics=(),
            contradictions=(),
            clarification_question="What would you like me to help you accomplish?",
            previous_objective=previous_objective,
        )

    explicit_no_execute = _contains(text, _NO_EXECUTE)
    execution_text = text
    for phrase in _NO_EXECUTE:
        execution_text = execution_text.replace(phrase, " ")
    explicit_execute = _contains(execution_text, _EXECUTE)
    explanation = _contains(text, _EXPLAIN) or _contains(text, _TEACH)
    example = _contains(text, _EXAMPLE)
    deploy = _contains(text, _DEPLOY)
    monitor = _contains(text, _MONITOR)
    test = _contains(text, _TEST)
    inspect = _contains(text, _INSPECT)
    change = _contains(text, _CHANGE)
    capability_discovery = _contains(text, _CAPABILITIES)
    project_idea = _contains(text, _PROJECT_IDEA)
    resume = command in _RESUME

    contradictions: list[str] = []
    if explicit_execute and explicit_no_execute:
        contradictions.append("execution requested and forbidden in the same message")
    if deploy and _contains(text, ("do not deploy", "don't deploy")):
        contradictions.append("deployment requested and forbidden in the same message")
    if change and explicit_no_execute and not (example or explanation):
        contradictions.append("repository-changing language conflicts with a no-change instruction")

    if contradictions:
        return ConversationDecision(
            intent=Intent.UNKNOWN,
            output_target=OutputTarget.NONE,
            execution_requested=False,
            repository_changes_allowed=False,
            explanation_requested=explanation,
            clarification_required=True,
            confidence=0.35,
            topics=topics,
            contradictions=tuple(contradictions),
            clarification_question=(
                "Should I only explain or show the proposed code in chat, or should I make "
                "real changes to the repository?"
            ),
            previous_objective=previous_objective,
        )

    if command in {"hi", "hello", "hey", "good morning", "good afternoon", "good evening"}:
        intent = Intent.GREETING
        target = OutputTarget.CHAT
    elif capability_discovery:
        intent = Intent.DISCOVER_CAPABILITIES
        target = OutputTarget.CHAT
    elif project_idea:
        intent = Intent.PROJECT_IDEA
        target = OutputTarget.CHAT
    elif resume and previous_objective:
        intent = Intent.RESUME
        target = OutputTarget.REPOSITORY
        explicit_execute = True
    elif resume:
        intent = Intent.RESUME
        target = OutputTarget.CHAT
    elif deploy:
        intent = Intent.DEPLOY
        target = OutputTarget.EXTERNAL_SYSTEM
    elif monitor:
        intent = Intent.MONITOR
        target = OutputTarget.EXTERNAL_SYSTEM
    elif test and not explicit_no_execute:
        intent = Intent.TEST
        target = OutputTarget.REPOSITORY
    elif inspect and not change:
        intent = Intent.INSPECT
        target = OutputTarget.REPOSITORY
    elif example and (explicit_no_execute or not explicit_execute):
        intent = Intent.SHOW_EXAMPLE
        target = OutputTarget.CHAT
    elif explanation and not explicit_execute:
        intent = Intent.TEACH if _contains(text, _TEACH) else Intent.EXPLAIN
        target = OutputTarget.CHAT
    elif change:
        intent = Intent.CHANGE_REPOSITORY
        target = OutputTarget.REPOSITORY
    elif command.endswith("?") or command.split(" ", 1)[0] in _QUESTION_START:
        intent = Intent.GENERAL_QUESTION
        target = OutputTarget.CHAT
    else:
        intent = Intent.UNKNOWN
        target = OutputTarget.CHAT

    execution_requested = (
        target in {OutputTarget.REPOSITORY, OutputTarget.EXTERNAL_SYSTEM}
        and not explicit_no_execute
        and (explicit_execute or intent in {Intent.DEPLOY, Intent.MONITOR, Intent.TEST})
    )
    repository_allowed = target == OutputTarget.REPOSITORY and execution_requested
    ambiguous_change = intent == Intent.CHANGE_REPOSITORY and not execution_requested
    missing_resume_context = intent == Intent.RESUME and previous_objective is None
    clarification = ambiguous_change or missing_resume_context or intent == Intent.UNKNOWN

    question = None
    if ambiguous_change:
        question = "Should I only show and explain the code, or should I edit the repository and verify the changes?"
    elif missing_resume_context:
        question = "Which project or unfinished task should I continue?"
    elif intent == Intent.UNKNOWN:
        question = "Tell me what you are trying to accomplish, and I will turn it into a clear next step."

    confidence = 0.94
    if clarification:
        confidence = 0.55
    elif len(topics) > 2:
        confidence = 0.75

    return ConversationDecision(
        intent=intent,
        output_target=target,
        execution_requested=execution_requested,
        repository_changes_allowed=repository_allowed,
        explanation_requested=explanation or example or capability_discovery,
        clarification_required=clarification,
        confidence=confidence,
        topics=topics,
        contradictions=(),
        clarification_question=question,
        previous_objective=previous_objective,
    )


def build_guided_reply(decision: ConversationDecision, *, user_name: str | None = None) -> str:
    """Return a safe, useful reply for common conversational states.

    The response educates first and asks only one meaningful follow-up. Execution
    claims remain outside this helper and must come from verified action evidence.
    """

    name = f" {user_name}" if user_name else ""
    if decision.intent == Intent.GREETING:
        return (
            f"Welcome{name}. I'm Amosclaud Autonomous. I can help you create, inspect, fix, "
            "verify, deploy, and monitor software. What would you like to accomplish today?"
        )
    if decision.intent == Intent.DISCOVER_CAPABILITIES:
        return (
            "Yes, I understand—you want to know what I can create and manage. I can build "
            "websites, mobile apps, APIs, AI agents, SaaS platforms, dashboards, business "
            "systems, automation tools, and complete GitHub projects. I can also inspect an "
            "existing repository, fix problems, run tests, prepare pull requests, deploy with "
            "your authorization, and monitor the result. What kind of project would you like "
            "me to help you create or improve?"
        )
    if decision.intent == Intent.PROJECT_IDEA:
        return (
            "Great. You do not need a complete plan yet. I can turn your idea into requirements, "
            "architecture, a repository, working code, tests, and a deployment plan. What problem "
            "should the project solve?"
        )
    if decision.intent == Intent.RESUME and decision.previous_objective:
        return (
            f"We were working on: {decision.previous_objective}. I will continue from the next "
            "unfinished step and preserve the decisions already made."
        )
    if decision.intent == Intent.RESUME:
        return decision.clarification_question or "Which unfinished task should I continue?"
    if decision.intent == Intent.GENERAL_QUESTION:
        return (
            "I understand your question. I will answer it clearly, connect it to what Amosclaud "
            "can do for you, and suggest one useful next step without starting repository work "
            "unless you ask me to proceed."
        )
    if decision.clarification_required and decision.clarification_question:
        return decision.clarification_question
    return "I understand the objective. I will respond with the clearest safe next step."

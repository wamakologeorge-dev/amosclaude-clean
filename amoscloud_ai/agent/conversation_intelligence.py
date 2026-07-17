"""Structured, deterministic conversation analysis for Amosclaud Autonomous.

The analyzer separates explanation, example generation, repository inspection, and
real execution intent before the autonomous runtime is allowed to act. It is a
conservative first layer: uncertainty and contradictory instructions produce a
clarification requirement instead of guessing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable


class Intent(StrEnum):
    GREETING = "greeting"
    EXPLAIN = "explain"
    SHOW_EXAMPLE = "show_example"
    TEACH = "teach"
    INSPECT = "inspect"
    CHANGE_REPOSITORY = "change_repository"
    TEST = "test"
    DEPLOY = "deploy"
    MONITOR = "monitor"
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
_EXPLAIN = ("explain", "what does", "what is", "why does", "walk me through")
_TEACH = ("teach me", "guide me", "show me how", "learn how", "step by step")
_EXAMPLE = ("show me code", "show an example", "give me an example", "sample code", "code example")
_INSPECT = ("inspect", "review", "diagnose", "check the code", "find the problem")
_CHANGE = ("build", "create", "fix", "change", "update", "refactor", "implement", "add", "remove", "delete")
_DEPLOY = ("deploy", "release", "publish to production")
_MONITOR = ("monitor", "watch status", "keep watching")
_TEST = ("run tests", "run the tests", "test the project", "verify the code")
_TOPIC_SPLIT = re.compile(r"(?:\.|;|\bbut\b|\balso\b|\bactually\b|\bnow\b)", re.IGNORECASE)


def _contains(text: str, phrases: Iterable[str]) -> bool:
    return any(phrase in text for phrase in phrases)


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
    """Classify one user message without authorizing any real-world action."""

    raw = " ".join((message or "").strip().split())
    text = raw.lower()
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
        )

    explicit_execute = _contains(text, _EXECUTE)
    explicit_no_execute = _contains(text, _NO_EXECUTE)
    explanation = _contains(text, _EXPLAIN) or _contains(text, _TEACH)
    example = _contains(text, _EXAMPLE)
    deploy = _contains(text, _DEPLOY)
    monitor = _contains(text, _MONITOR)
    test = _contains(text, _TEST)
    inspect = _contains(text, _INSPECT)
    change = _contains(text, _CHANGE)

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
        )

    if text in {"hi", "hello", "hey", "good morning", "good afternoon", "good evening"}:
        intent = Intent.GREETING
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
    elif previous_objective and text in {"proceed", "do it", "continue", "start"}:
        intent = Intent.CHANGE_REPOSITORY
        target = OutputTarget.REPOSITORY
        explicit_execute = True
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
    clarification = ambiguous_change or intent == Intent.UNKNOWN

    question = None
    if ambiguous_change:
        question = "Should I only show and explain the code, or should I edit the repository and verify the changes?"
    elif intent == Intent.UNKNOWN:
        question = "What result do you want, and should I answer in chat or perform work in the repository?"

    confidence = 0.92
    if clarification:
        confidence = 0.55
    elif len(topics) > 2:
        confidence = 0.75

    return ConversationDecision(
        intent=intent,
        output_target=target,
        execution_requested=execution_requested,
        repository_changes_allowed=repository_allowed,
        explanation_requested=explanation or example,
        clarification_required=clarification,
        confidence=confidence,
        topics=topics,
        contradictions=(),
        clarification_question=question,
    )

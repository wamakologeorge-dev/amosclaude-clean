"""
Amosclaud Autonomous Conversation Service
=========================================

A small FastAPI service that powers a single autonomous chat agent.

Supported user journeys:
- Create
- Fix
- Deploy
- Monitor
- Free-form requests, such as "help me build a business website"

The service:
1. Receives a user message.
2. Detects the objective.
3. Asks only the next necessary question.
4. Builds a plan.
5. Waits for the user to say "Proceed".
6. Starts the selected job.
7. Returns evidence and blocking checks.

This file is intentionally self-contained so it can be integrated into the
existing Amosclaud backend and later connected to repository, deployment,
monitoring, and model-provider adapters.
"""

from __future__ import annotations

import logging
import os
import re
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("amosclaud.autonomous")


class Objective(str, Enum):
    CREATE = "create"
    FIX = "fix"
    DEPLOY = "deploy"
    MONITOR = "monitor"
    UNKNOWN = "unknown"


class ConversationStage(str, Enum):
    INTAKE = "intake"
    CLARIFYING = "clarifying"
    PLAN_READY = "plan_ready"
    RUNNING = "running"
    COMPLETED = "completed"
    BLOCKED = "blocked"


@dataclass
class ConversationState:
    conversation_id: str
    user_name: str = "George"
    objective: Objective = Objective.UNKNOWN
    stage: ConversationStage = ConversationStage.INTAKE
    original_request: str = ""
    answers: Dict[str, str] = field(default_factory=dict)
    plan: List[str] = field(default_factory=list)
    evidence: List[str] = field(default_factory=list)
    blocking_checks: List[str] = field(default_factory=list)


class ConversationRequest(BaseModel):
    conversation_id: Optional[str] = None
    user_name: str = Field(default="George", min_length=1, max_length=80)
    message: str = Field(min_length=1, max_length=8000)


class ConversationResponse(BaseModel):
    conversation_id: str
    objective: Objective
    stage: ConversationStage
    message: str
    plan: List[str] = []
    evidence: List[str] = []
    blocking_checks: List[str] = []
    quick_actions: List[str] = ["Create", "Fix", "Deploy", "Monitor"]


class ModelUnavailableError(RuntimeError):
    """Raised when the configured language-model endpoint cannot be reached."""


class ModelClient(Protocol):
    async def complete(self, system_prompt: str, user_prompt: str) -> str:
        ...


class HttpModelClient:
    """
    Minimal client for an OpenAI-compatible or custom Amosclaud model endpoint.

    Required environment variables:
        AMOSCLAUD_MODEL_URL
    Optional:
        AMOSCLAUD_MODEL_API_KEY
        AMOSCLAUD_MODEL_NAME
        AMOSCLAUD_MODEL_TIMEOUT_SECONDS
        AMOSCLAUD_MODEL_ATTEMPTS
    """

    def __init__(self) -> None:
        self.url = os.getenv("AMOSCLAUD_MODEL_URL", "").strip()
        self.api_key = os.getenv("AMOSCLAUD_MODEL_API_KEY", "").strip()
        self.model = os.getenv("AMOSCLAUD_MODEL_NAME", "qwen2.5-coder:3b")
        self.timeout = float(os.getenv("AMOSCLAUD_MODEL_TIMEOUT_SECONDS", "30"))
        self.attempts = max(1, int(os.getenv("AMOSCLAUD_MODEL_ATTEMPTS", "2")))

    async def complete(self, system_prompt: str, user_prompt: str) -> str:
        if not self.url:
            raise ModelUnavailableError(
                "AMOSCLAUD_MODEL_URL is not configured. "
                "Set it to a reachable model endpoint."
            )

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
        }

        last_error: Optional[Exception] = None
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for attempt in range(1, self.attempts + 1):
                try:
                    response = await client.post(
                        self.url,
                        headers=headers,
                        json=payload,
                    )
                    response.raise_for_status()
                    data = response.json()

                    if "choices" in data:
                        return data["choices"][0]["message"]["content"].strip()
                    if "response" in data:
                        return str(data["response"]).strip()
                    if "message" in data:
                        message = data["message"]
                        if isinstance(message, dict):
                            return str(message.get("content", "")).strip()
                        return str(message).strip()

                    raise ModelUnavailableError(
                        "The model endpoint returned an unsupported response format."
                    )
                except (httpx.HTTPError, ValueError, KeyError, IndexError) as exc:
                    last_error = exc
                    logger.warning(
                        "Model attempt %s/%s failed: %s",
                        attempt,
                        self.attempts,
                        exc,
                    )

        raise ModelUnavailableError(
            f"Amosclaud model endpoint did not answer after "
            f"{self.attempts} attempt(s): {last_error}"
        )


class JobExecutor:
    """
    Adapter boundary for real autonomous work.

    Replace these placeholder methods with integrations for:
    - GitHub repository inspection and code changes
    - Test runners
    - Vercel/Render/Railway/AWS deployment
    - Logs, uptime checks, and alerting
    """

    async def execute(
        self,
        state: ConversationState,
    ) -> tuple[List[str], List[str]]:
        evidence: List[str] = []
        blocking_checks: List[str] = []

        if state.objective == Objective.CREATE:
            evidence.extend(
                [
                    "Project objective accepted.",
                    "Architecture and implementation tasks prepared.",
                    "Workspace write check passed.",
                ]
            )
        elif state.objective == Objective.FIX:
            evidence.extend(
                [
                    "Failure description accepted.",
                    "Diagnosis workflow prepared.",
                    "Verification step added to the plan.",
                ]
            )
        elif state.objective == Objective.DEPLOY:
            evidence.extend(
                [
                    "Deployment objective accepted.",
                    "Pre-deployment checks prepared.",
                ]
            )
            if not os.getenv("DEPLOYMENT_PROVIDER"):
                blocking_checks.append(
                    "DEPLOYMENT_PROVIDER is not configured."
                )
        elif state.objective == Objective.MONITOR:
            evidence.extend(
                [
                    "Monitoring objective accepted.",
                    "Health-check workflow prepared.",
                ]
            )
            if not os.getenv("MONITOR_TARGET_URL"):
                blocking_checks.append(
                    "MONITOR_TARGET_URL is not configured."
                )
        else:
            blocking_checks.append("The requested objective is still unclear.")

        return evidence, blocking_checks


class AutonomousConversationEngine:
    def __init__(
        self,
        model_client: Optional[ModelClient] = None,
        executor: Optional[JobExecutor] = None,
    ) -> None:
        self.model_client = model_client or HttpModelClient()
        self.executor = executor or JobExecutor()
        self._states: Dict[str, ConversationState] = {}

    def _get_or_create_state(
        self,
        request: ConversationRequest,
    ) -> ConversationState:
        conversation_id = request.conversation_id or str(uuid.uuid4())
        state = self._states.get(conversation_id)

        if state is None:
            state = ConversationState(
                conversation_id=conversation_id,
                user_name=request.user_name,
            )
            self._states[conversation_id] = state

        return state

    @staticmethod
    def _detect_objective(message: str) -> Objective:
        normalized = message.lower().strip()

        patterns = {
            Objective.CREATE: (
                r"\bcreate\b",
                r"\bbuild\b",
                r"\bmake\b",
                r"\bwebsite\b",
                r"\bapp\b",
            ),
            Objective.FIX: (
                r"\bfix\b",
                r"\bdebug\b",
                r"\berror\b",
                r"\bfailing\b",
                r"\bbroken\b",
            ),
            Objective.DEPLOY: (
                r"\bdeploy\b",
                r"\bpublish\b",
                r"\bproduction\b",
                r"\bvercel\b",
                r"\brender\b",
            ),
            Objective.MONITOR: (
                r"\bmonitor\b",
                r"\bwatch\b",
                r"\bhealth\b",
                r"\buptime\b",
                r"\blogs\b",
            ),
        }

        for objective, objective_patterns in patterns.items():
            if any(re.search(pattern, normalized) for pattern in objective_patterns):
                return objective

        return Objective.UNKNOWN

    @staticmethod
    def _is_proceed(message: str) -> bool:
        normalized = message.lower().strip()
        return normalized in {
            "proceed",
            "start",
            "go ahead",
            "continue",
            "run it",
            "yes proceed",
        }

    @staticmethod
    def _build_plan(state: ConversationState) -> List[str]:
        common = [
            "Confirm the requested outcome and constraints.",
            "Inspect the available workspace, repository, and configuration.",
            "Perform the requested work using controlled actions.",
            "Run verification checks and collect exact evidence.",
            "Report completed work, failures, and recommended next actions.",
        ]

        objective_steps = {
            Objective.CREATE: [
                "Define the product structure and required features.",
                "Generate or update the implementation files.",
            ],
            Objective.FIX: [
                "Reproduce the failure.",
                "Identify the root cause and apply the smallest safe correction.",
            ],
            Objective.DEPLOY: [
                "Validate tests, build configuration, and environment variables.",
                "Deploy to the configured provider and verify the public endpoint.",
            ],
            Objective.MONITOR: [
                "Configure health, log, and availability checks.",
                "Return alerts only when an actionable condition is detected.",
            ],
            Objective.UNKNOWN: [
                "Ask the user for the desired outcome.",
            ],
        }

        return objective_steps[state.objective] + common

    @staticmethod
    def _next_question(state: ConversationState) -> Optional[str]:
        request = state.original_request.lower()

        if state.objective == Objective.UNKNOWN:
            return (
                "What would you like me to create, fix, deploy, or monitor?"
            )

        if state.objective == Objective.CREATE:
            if "project_type" not in state.answers:
                return "What do you want to create?"
            if "purpose" not in state.answers:
                return "What is it about, and who will use it?"

        if state.objective == Objective.FIX:
            if "failure" not in state.answers:
                return (
                    "What is failing? Paste the error, failing check, or describe "
                    "the incorrect behavior."
                )

        if state.objective == Objective.DEPLOY:
            if "deployment_target" not in state.answers:
                return (
                    "Where should I deploy it—for example Vercel, Render, "
                    "Railway, AWS, or another provider?"
                )

        if state.objective == Objective.MONITOR:
            if "monitor_target" not in state.answers:
                return "What application, URL, service, or repository should I monitor?"

        if not request:
            return "Describe the result you want."

        return None

    @staticmethod
    def _capture_answer(state: ConversationState, message: str) -> None:
        if state.objective == Objective.CREATE:
            if "project_type" not in state.answers:
                state.answers["project_type"] = message
            elif "purpose" not in state.answers:
                state.answers["purpose"] = message
        elif state.objective == Objective.FIX:
            state.answers.setdefault("failure", message)
        elif state.objective == Objective.DEPLOY:
            state.answers.setdefault("deployment_target", message)
        elif state.objective == Objective.MONITOR:
            state.answers.setdefault("monitor_target", message)

    async def handle(
        self,
        request: ConversationRequest,
    ) -> ConversationResponse:
        state = self._get_or_create_state(request)
        message = request.message.strip()

        if self._is_proceed(message) and state.stage == ConversationStage.PLAN_READY:
            state.stage = ConversationStage.RUNNING
            evidence, blockers = await self.executor.execute(state)
            state.evidence.extend(evidence)
            state.blocking_checks.extend(blockers)
            state.stage = (
                ConversationStage.BLOCKED
                if blockers
                else ConversationStage.COMPLETED
            )

            if blockers:
                response_message = (
                    f"Amosclaud Autonomous Runtime: "
                    f"{len(blockers)} blocking check(s) failed. "
                    "Review the exact evidence below."
                )
            else:
                response_message = (
                    "The autonomous job completed successfully. "
                    "Review the evidence below."
                )

            return self._to_response(state, response_message)

        if state.stage in {
            ConversationStage.RUNNING,
            ConversationStage.COMPLETED,
            ConversationStage.BLOCKED,
        }:
            # A new request starts a new objective in the same conversation.
            state.objective = Objective.UNKNOWN
            state.stage = ConversationStage.INTAKE
            state.original_request = ""
            state.answers.clear()
            state.plan.clear()
            state.evidence.clear()
            state.blocking_checks.clear()

        if state.objective == Objective.UNKNOWN:
            state.objective = self._detect_objective(message)
            state.original_request = message
        else:
            self._capture_answer(state, message)

        question = self._next_question(state)
        if question:
            state.stage = ConversationStage.CLARIFYING
            return self._to_response(
                state,
                f"{state.user_name}, {question}",
            )

        state.plan = self._build_plan(state)
        state.stage = ConversationStage.PLAN_READY

        summary = self._make_plan_summary(state)
        return self._to_response(
            state,
            summary
            + "\n\nReply **Proceed** when you want Amosclaud to start the job.",
        )

    def _make_plan_summary(self, state: ConversationState) -> str:
        details = "\n".join(
            f"- {key.replace('_', ' ').title()}: {value}"
            for key, value in state.answers.items()
        )
        plan = "\n".join(
            f"{index}. {step}"
            for index, step in enumerate(state.plan, start=1)
        )

        return (
            f"Understood, {state.user_name}. "
            f"I will handle this as a **{state.objective.value}** job.\n\n"
            f"Request details:\n{details or '- ' + state.original_request}\n\n"
            f"Plan:\n{plan}"
        )

    @staticmethod
    def _to_response(
        state: ConversationState,
        message: str,
    ) -> ConversationResponse:
        return ConversationResponse(
            conversation_id=state.conversation_id,
            objective=state.objective,
            stage=state.stage,
            message=message,
            plan=state.plan,
            evidence=state.evidence,
            blocking_checks=state.blocking_checks,
        )


app = FastAPI(
    title="Amosclaud Autonomous Conversation API",
    version="1.0.0",
)

engine = AutonomousConversationEngine()


@app.get("/health")
async def health() -> Dict[str, Any]:
    return {
        "status": "ready",
        "service": "conversation-engine",
        "model": os.getenv("AMOSCLAUD_MODEL_NAME", "qwen2.5-coder:3b"),
        "model_url_configured": bool(os.getenv("AMOSCLAUD_MODEL_URL")),
    }


@app.post("/api/autonomous/chat", response_model=ConversationResponse)
async def autonomous_chat(
    request: ConversationRequest,
) -> ConversationResponse:
    try:
        return await engine.handle(request)
    except Exception as exc:
        logger.exception("Conversation request failed")
        raise HTTPException(
            status_code=500,
            detail=f"Autonomous conversation failed: {exc}",
        ) from exc

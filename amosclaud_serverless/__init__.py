"""Bounded serverless adapter governed by Amosclaud Autonomous."""

from __future__ import annotations

from enum import Enum
from typing import Any

import httpx
from pydantic import BaseModel, Field

from shared.runtime import ServiceName, platform_endpoints
from shared.statuses import ExecutionStatus


class ProviderTarget(str, Enum):
    PLATFORM = "platform"
    MODEL = "model"
    CREDENTIAL_AUTHORITY = "credential-authority"
    METRICS = "metrics"


class FunctionOperation(str, Enum):
    PLATFORM_HEALTH = "platform.health"
    AGENT_RUN = "agent.run"
    FIXER_RUN = "fixer.run"
    REPOSITORY_INSPECT = "repository.inspect"
    MODEL_CHAT = "model.chat"
    CREDENTIAL_VALIDATE = "credential.validate"
    METRICS_SNAPSHOT = "metrics.snapshot"


class FunctionRequest(BaseModel):
    operation: FunctionOperation
    payload: dict[str, Any] = Field(default_factory=dict)
    repository_id: int | None = Field(default=None, ge=1)
    pull_request_id: int | None = Field(default=None, ge=1)
    branch: str | None = Field(default=None, max_length=255)
    request_id: str | None = Field(default=None, max_length=128)
    timeout_seconds: float = Field(default=30.0, gt=0, le=300)


class FunctionResult(BaseModel):
    accepted: bool
    operation: FunctionOperation
    target: ProviderTarget
    status: ExecutionStatus
    request_id: str | None = None
    status_code: int | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


_OPERATION_ROUTES: dict[FunctionOperation, tuple[ProviderTarget, str, str]] = {
    FunctionOperation.PLATFORM_HEALTH: (ProviderTarget.PLATFORM, "GET", "/health"),
    FunctionOperation.AGENT_RUN: (ProviderTarget.PLATFORM, "POST", "/api/v1/agent/run"),
    FunctionOperation.FIXER_RUN: (ProviderTarget.PLATFORM, "POST", "/api/v1/agent/run"),
    FunctionOperation.REPOSITORY_INSPECT: (ProviderTarget.PLATFORM, "POST", "/api/v1/agent/run"),
    FunctionOperation.MODEL_CHAT: (ProviderTarget.MODEL, "POST", "/v1/chat/completions"),
    FunctionOperation.CREDENTIAL_VALIDATE: (
        ProviderTarget.CREDENTIAL_AUTHORITY,
        "POST",
        "/api-keys/validate",
    ),
    FunctionOperation.METRICS_SNAPSHOT: (ProviderTarget.METRICS, "GET", "/v1/ssy"),
}

_SERVICE_MAP = {
    ProviderTarget.PLATFORM: ServiceName.PLATFORM,
    ProviderTarget.MODEL: ServiceName.MODEL,
    ProviderTarget.CREDENTIAL_AUTHORITY: ServiceName.CREDENTIAL_AUTHORITY,
    ProviderTarget.METRICS: ServiceName.METRICS,
}


class ServerlessDispatcher:
    """Dispatch approved operations to Amosclaud services using shared endpoints."""

    def __init__(self, *, api_key: str | None = None, model_token: str | None = None) -> None:
        self.api_key = api_key
        self.model_token = model_token

    def _payload(self, request: FunctionRequest) -> dict[str, Any]:
        payload = dict(request.payload)
        if request.repository_id is not None:
            payload.setdefault("repository_id", request.repository_id)
        if request.pull_request_id is not None:
            payload.setdefault("pull_request_id", request.pull_request_id)
        if request.branch is not None:
            payload.setdefault("branch", request.branch)
        if request.operation is FunctionOperation.FIXER_RUN:
            payload.setdefault("mode", "fix")
        elif request.operation is FunctionOperation.REPOSITORY_INSPECT:
            payload.setdefault("mode", "inspect")
        return payload

    async def dispatch(self, request: FunctionRequest) -> FunctionResult:
        target, method, path = _OPERATION_ROUTES[request.operation]
        endpoint = platform_endpoints()[_SERVICE_MAP[target]]
        headers: dict[str, str] = {}
        token = self.model_token if target is ProviderTarget.MODEL else self.api_key
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            async with httpx.AsyncClient(timeout=request.timeout_seconds) as client:
                response = await client.request(
                    method,
                    f"{endpoint.base_url}{path}",
                    headers=headers,
                    json=self._payload(request) if method != "GET" else None,
                )
            try:
                body = response.json()
                data = body if isinstance(body, dict) else {"result": body}
            except ValueError:
                data = {"text": response.text[:4000]}
            passed = 200 <= response.status_code < 300
            return FunctionResult(
                accepted=passed,
                operation=request.operation,
                target=target,
                status=ExecutionStatus.PASSED if passed else ExecutionStatus.FAILED,
                request_id=request.request_id,
                status_code=response.status_code,
                data=data,
                error=None if passed else data.get("detail", "service request failed"),
            )
        except httpx.HTTPError as exc:
            return FunctionResult(
                accepted=False,
                operation=request.operation,
                target=target,
                status=ExecutionStatus.FAILED,
                request_id=request.request_id,
                error=str(exc),
            )


__all__ = [
    "FunctionOperation",
    "FunctionRequest",
    "FunctionResult",
    "ProviderTarget",
    "ServerlessDispatcher",
]

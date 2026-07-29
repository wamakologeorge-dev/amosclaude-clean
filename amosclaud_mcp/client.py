"""HTTP client used by the Amosclaud MCP server."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

import httpx

from sitecustomize import normalize_public_amosclaud_url

TERMINAL_PIPELINE_STATES = {"success", "failed", "cancelled"}


class AmosclaudMCPError(RuntimeError):
    """Raised when Amosclaud rejects or cannot complete an MCP operation."""


@dataclass(frozen=True)
class AmosclaudClientConfig:
    """Connection settings for one Amosclaud installation."""

    base_url: str
    autonomous_key: str | None
    timeout_seconds: float = 60.0

    @classmethod
    def from_environment(cls) -> "AmosclaudClientConfig":
        raw_url = os.getenv("AMOSCLAUD_API_URL", "https://www.amosclaud.com").strip()
        if not raw_url:
            raise AmosclaudMCPError("AMOSCLAUD_API_URL cannot be empty")
        try:
            timeout = max(1.0, float(os.getenv("AMOSCLAUD_MCP_TIMEOUT", "60")))
        except ValueError as exc:
            raise AmosclaudMCPError("AMOSCLAUD_MCP_TIMEOUT must be a number") from exc
        return cls(
            base_url=normalize_public_amosclaud_url(raw_url),
            autonomous_key=(
                os.getenv("AMOSCLAUD_AUTONOMOUS_KEY") or os.getenv("AMOSCLAUD_MCP_API_KEY") or None
            ),
            timeout_seconds=timeout,
        )


class AmosclaudClient:
    """Small, testable client for the public Amosclaud Autonomous API."""

    def __init__(
        self,
        config: AmosclaudClientConfig | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.config = config or AmosclaudClientConfig.from_environment()
        self._client = httpx.Client(
            base_url=self.config.base_url,
            timeout=self.config.timeout_seconds,
            transport=transport,
            follow_redirects=True,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "AmosclaudClient":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def _headers(self, *, protected: bool) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "User-Agent": "amosclaud-mcp/1.0",
        }
        if protected:
            if not self.config.autonomous_key:
                raise AmosclaudMCPError(
                    "Set AMOSCLAUD_AUTONOMOUS_KEY before using protected Amosclaud MCP tools"
                )
            headers["Authorization"] = f"Bearer {self.config.autonomous_key}"
        return headers

    def _request(
        self,
        method: str,
        path: str,
        *,
        protected: bool = False,
        json: dict[str, Any] | None = None,
    ) -> Any:
        try:
            response = self._client.request(
                method,
                path,
                headers=self._headers(protected=protected),
                json=json,
            )
        except httpx.HTTPError as exc:
            raise AmosclaudMCPError(
                f"Could not reach Amosclaud at {self.config.base_url}: {type(exc).__name__}"
            ) from exc

        try:
            payload: Any = response.json()
        except ValueError:
            payload = {"detail": response.text.strip() or "Non-JSON response"}

        if response.is_error:
            if isinstance(payload, dict):
                detail = payload.get("detail") or payload.get("message") or payload.get("error")
            else:
                detail = None
            raise AmosclaudMCPError(
                f"Amosclaud request failed ({response.status_code}): "
                f"{detail or response.reason_phrase}"
            )
        return payload

    def status(self) -> dict[str, Any]:
        """Return web and Autonomous readiness without exposing credentials."""

        health = self._request("GET", "/health")
        readiness = self._request("GET", "/ready")
        return {
            "base_url": self.config.base_url,
            "authenticated": bool(self.config.autonomous_key),
            "health": health,
            "readiness": readiness,
        }

    def agent_profile(self) -> dict[str, Any]:
        return self._request("GET", "/api/v1/agent")

    def run_autonomous(
        self,
        *,
        objective: str,
        mode: str = "fix",
        branch: str = "main",
        repository_id: int | None = None,
        apply_changes: bool = True,
        extra_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        cleaned_objective = objective.strip()
        if not cleaned_objective:
            raise AmosclaudMCPError("objective cannot be empty")
        normalized_mode = mode.strip().lower()
        allowed_modes = {"autonomous-check", "build", "fix", "deploy", "monitor"}
        if normalized_mode not in allowed_modes:
            raise AmosclaudMCPError(f"mode must be one of: {', '.join(sorted(allowed_modes))}")
        metadata: dict[str, Any] = {
            "source": "amosclaud-mcp",
            "mcp_client": True,
            "use_agent": True,
            "apply_changes": bool(apply_changes),
        }
        if repository_id is not None:
            if repository_id <= 0:
                raise AmosclaudMCPError("repository_id must be a positive integer")
            metadata["repository_id"] = repository_id
        if extra_metadata:
            metadata.update(extra_metadata)

        return self._request(
            "POST",
            "/api/v1/agent/run",
            protected=True,
            json={
                "mode": normalized_mode,
                "objective": cleaned_objective,
                "branch": branch.strip() or "main",
                "metadata": metadata,
            },
        )

    def inspect_repository(
        self,
        *,
        repository_id: int,
        objective: str = "Inspect this repository and report the first verified blocker.",
        branch: str = "main",
    ) -> dict[str, Any]:
        return self.run_autonomous(
            objective=objective,
            mode="autonomous-check",
            branch=branch,
            repository_id=repository_id,
            apply_changes=False,
        )

    def get_pipeline(self, pipeline_id: str) -> dict[str, Any]:
        cleaned = pipeline_id.strip()
        if not cleaned:
            raise AmosclaudMCPError("pipeline_id cannot be empty")
        return self._request(
            "GET",
            f"/api/v1/pipelines/{cleaned}",
            protected=True,
        )

    def list_recent_pipelines(self) -> list[dict[str, Any]]:
        payload = self._request("GET", "/api/v1/pipelines", protected=True)
        if not isinstance(payload, list):
            raise AmosclaudMCPError("Amosclaud returned an invalid pipeline list")
        return payload

    def wait_for_pipeline(
        self,
        pipeline_id: str,
        *,
        timeout_seconds: int = 120,
        poll_interval_seconds: float = 2.0,
    ) -> dict[str, Any]:
        timeout_seconds = min(max(int(timeout_seconds), 1), 300)
        poll_interval_seconds = min(max(float(poll_interval_seconds), 0.5), 10.0)
        deadline = time.monotonic() + timeout_seconds
        latest: dict[str, Any] = {}

        while time.monotonic() < deadline:
            latest = self.get_pipeline(pipeline_id)
            if str(latest.get("status", "")).lower() in TERMINAL_PIPELINE_STATES:
                return latest
            time.sleep(poll_interval_seconds)

        raise AmosclaudMCPError(
            f"Pipeline {pipeline_id} did not finish within {timeout_seconds} seconds"
        )

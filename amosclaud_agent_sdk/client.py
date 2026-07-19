"""Dependency-free client for Amosclaud Autonomous on Amosclaud.com."""
from __future__ import annotations
import json
import os
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
from .errors import AmosclaudSDKError

class AmosclaudAgentError(AmosclaudSDKError):
    """A safe, user-facing Amosclaud API failure."""

@dataclass(slots=True)
class AmosclaudAgentClient:
    """Connect Python to the governed Amosclaud agent runtime.

    Authentication is resolved in priority order: constructor argument first,
    then the ``AMOSCLAUD_API_KEY`` / ``AMOSCLAUD_SESSION`` environment variables.
    At least one of ``api_key`` or ``session_cookie`` must be set before making
    authenticated requests.

    Args:
        base_url: Root URL of the Amosclaud service. Trailing slashes are stripped.
        api_key: Bearer token sent as ``Authorization: Bearer <key>``.
        session_cookie: Value of the ``amos_session`` cookie for web-session auth.
        timeout: Per-request socket timeout in seconds.
    """
    base_url: str = "https://www.amosclaud.com"
    api_key: str | None = None
    session_cookie: str | None = None
    timeout: float = 30.0

    def __post_init__(self) -> None:
        self.base_url = (self.base_url or "https://www.amosclaud.com").rstrip("/")
        self.api_key = self.api_key or os.getenv("AMOSCLAUD_API_KEY")
        self.session_cookie = self.session_cookie or os.getenv("AMOSCLAUD_SESSION")

    def profile(self) -> dict[str, Any]:
        """Return the authenticated agent's profile from the Amosclaud API."""
        return self._request("GET", "/api/v1/agent")

    def readiness(self) -> dict[str, Any]:
        """Return the service's readiness probe response.

        Useful as a lightweight health check before submitting work.
        """
        return self._request("GET", "/api/v1/agent/readiness")

    def run(
        self,
        objective: str,
        *,
        mode: str = "autonomous-check",
        branch: str = "main",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Submit an objective and return immediately with the accepted pipeline reference.

        Args:
            objective: Plain-language description of the work to perform.
            mode: Execution mode, e.g. ``"autonomous-check"`` or ``"build"``.
            branch: Repository branch the agent should operate on.
            metadata: Arbitrary key/value pairs forwarded to the pipeline context.

        Returns:
            The API response dict, which includes at minimum a ``pipeline_id``
            and an initial ``status`` field.

        Raises:
            ValueError: If ``objective`` is blank.
            AmosclaudAgentError: On HTTP or network failure.
        """
        if not objective.strip():
            raise ValueError("objective is required")
        return self._request("POST", "/api/v1/agent/run", {"objective": objective, "mode": mode, "branch": branch, "metadata": dict(metadata or {})})

    def pipeline(self, pipeline_id: str) -> dict[str, Any]:
        """Fetch the current state of a pipeline by its identifier.

        Args:
            pipeline_id: Opaque pipeline ID as returned by :meth:`run`.

        Returns:
            The pipeline status dict. The ``status`` field is one of
            ``"success"``, ``"failed"``, ``"cancelled"``, or a running state.
        """
        return self._request("GET", f"/api/v1/pipelines/{quote(pipeline_id, safe='')}")

    def run_and_wait(
        self,
        objective: str,
        *,
        mode: str = "autonomous-check",
        branch: str = "main",
        metadata: dict[str, Any] | None = None,
        poll_seconds: float = 1.0,
        max_wait_seconds: float = 300.0,
    ) -> dict[str, Any]:
        """Submit an objective and block until the pipeline reaches a terminal state.

        Polls :meth:`pipeline` every ``poll_seconds`` seconds. Returns immediately
        if the initial :meth:`run` response already carries a terminal status.

        Args:
            objective: Work description forwarded to :meth:`run`.
            mode: Execution mode forwarded to :meth:`run`.
            branch: Repository branch forwarded to :meth:`run`.
            metadata: Context metadata forwarded to :meth:`run`.
            poll_seconds: Seconds between status polls (minimum 0.1).
            max_wait_seconds: Maximum total blocking time before raising.

        Returns:
            The terminal pipeline status dict.

        Raises:
            AmosclaudAgentError: If the pipeline ID is missing from the initial
                response, or if ``max_wait_seconds`` elapses without a terminal state.
        """
        accepted = self.run(objective, mode=mode, branch=branch, metadata=metadata)
        if accepted.get("status") in {"success", "failed", "cancelled"}:
            return accepted
        pipeline_id = str(accepted.get("pipeline_id") or "")
        if not pipeline_id:
            raise AmosclaudAgentError("Amosclaud did not return a pipeline identifier")
        deadline = time.monotonic() + max_wait_seconds
        while time.monotonic() < deadline:
            result = self.pipeline(pipeline_id)
            if result.get("status") in {"success", "failed", "cancelled"}:
                return result
            time.sleep(max(0.1, poll_seconds))
        raise AmosclaudAgentError(f"Pipeline {pipeline_id} did not finish within {max_wait_seconds:g} seconds")

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Send an authenticated HTTP request and return the parsed JSON response.

        Sends ``api_key`` as a Bearer token and ``session_cookie`` as the
        ``amos_session`` cookie when present. Both may be set simultaneously.

        Args:
            method: HTTP verb (``"GET"``, ``"POST"``, etc.).
            path: URL path appended to ``base_url``.
            payload: Optional dict serialised as JSON in the request body.

        Returns:
            Parsed JSON response as a ``dict``.

        Raises:
            AmosclaudAgentError: On HTTP errors, network failures, or non-dict responses.
        """
        headers = {"Accept": "application/json", "User-Agent": "amosclaud-agent-sdk"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if self.session_cookie:
            headers["Cookie"] = f"amos_session={self.session_cookie}"
        data = None
        if payload is not None:
            data = json.dumps(payload).encode()
            headers["Content-Type"] = "application/json"
        request = Request(self.base_url + path, data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode()
        except HTTPError as error:
            raw = error.read().decode(errors="replace")
            try:
                detail = json.loads(raw).get("detail", raw)
            except json.JSONDecodeError:
                detail = raw
            raise AmosclaudAgentError(f"Amosclaud request failed ({error.code}): {detail}") from error
        except (URLError, TimeoutError) as error:
            raise AmosclaudAgentError(f"Cannot reach {self.base_url}: {error}") from error
        try:
            result = json.loads(raw or "{}")
        except json.JSONDecodeError as error:
            raise AmosclaudAgentError("Amosclaud returned a non-JSON response") from error
        if not isinstance(result, dict):
            raise AmosclaudAgentError("Amosclaud returned an invalid response contract")
        return result

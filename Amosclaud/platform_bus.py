"""Secure in-process byte command bus for the Amosclaud platform.

The API gateway remains the authenticated public boundary. This module turns
validated gateway requests into integrity-checked internal commands and keeps
AutonomousJob/CIPipeline state in the shared SQLAlchemy database authoritative.
"""

from __future__ import annotations

import datetime
import hashlib
import hmac
import json
import os
import threading
import time
from collections import deque
from typing import Any

from sqlalchemy import select

from Amosclaud.byte.core import ByteFrame
from Amosclaud.byte.router import ByteRouter
from Amosclaud.byte.system import ByteSystem
from database.models import AutonomousJob, AutonomousJobStatus, CIPipeline, CIStatus, Repository
from database.session import create_database, session_scope

_SIGNATURE_HEADER = "amosclaud-signature"
_NONCE_HEADER = "amosclaud-nonce"
_EXPIRES_HEADER = "amosclaud-expires"
_ALLOWED_JOB_TRANSITIONS: dict[AutonomousJobStatus, set[AutonomousJobStatus]] = {
    AutonomousJobStatus.QUEUED: {
        AutonomousJobStatus.INSPECTING,
        AutonomousJobStatus.CANCELLED,
        AutonomousJobStatus.FAILED,
    },
    AutonomousJobStatus.INSPECTING: {
        AutonomousJobStatus.REPAIRING,
        AutonomousJobStatus.VERIFYING,
        AutonomousJobStatus.FAILED,
    },
    AutonomousJobStatus.REPAIRING: {
        AutonomousJobStatus.VERIFYING,
        AutonomousJobStatus.FAILED,
    },
    AutonomousJobStatus.VERIFYING: {
        AutonomousJobStatus.PASSED,
        AutonomousJobStatus.FAILED,
    },
    AutonomousJobStatus.PASSED: set(),
    AutonomousJobStatus.FAILED: set(),
    AutonomousJobStatus.CANCELLED: set(),
}


def _canonical_signature_input(frame: ByteFrame) -> bytes:
    headers = {
        key: value
        for key, value in frame.headers.items()
        if key != _SIGNATURE_HEADER
    }
    value = {
        "route": frame.route,
        "frame_id": frame.frame_id,
        "created_ns": frame.created_ns,
        "headers": headers,
        "payload_sha256": frame.sha256,
    }
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")


def signed_frame(
    route: str,
    payload: dict[str, Any],
    *,
    secret: bytes,
    ttl_seconds: int = 60,
    nonce: str | None = None,
) -> ByteFrame:
    """Create a short-lived authenticated internal command frame."""
    if not secret:
        raise ValueError("a non-empty byte-bus secret is required")
    expires = int(time.time()) + max(1, min(ttl_seconds, 300))
    nonce_value = nonce or os.urandom(16).hex()
    frame = ByteFrame.from_json(
        route,
        payload,
        headers={_NONCE_HEADER: nonce_value, _EXPIRES_HEADER: str(expires)},
    )
    signature = hmac.new(
        secret,
        _canonical_signature_input(frame),
        hashlib.sha256,
    ).hexdigest()
    return ByteFrame(
        route=frame.route,
        payload=frame.payload,
        frame_id=frame.frame_id,
        created_ns=frame.created_ns,
        headers={**frame.headers, _SIGNATURE_HEADER: signature},
        version=frame.version,
    )


class PlatformByteBus:
    """Database-backed internal command bus for repositories, jobs, and CI."""

    def __init__(self, secret: bytes, *, replay_cache_size: int = 10_000) -> None:
        if not secret:
            raise ValueError("a non-empty byte-bus secret is required")
        self._secret = secret
        self._seen: set[str] = set()
        self._seen_order: deque[str] = deque()
        self._replay_cache_size = replay_cache_size
        self._lock = threading.RLock()
        self.router = ByteRouter()
        self.system = ByteSystem(self.router, name="amosclaud-platform-bus")
        self.router.register("platform.health", self._health)
        self.router.register("platform.repository.summary", self._repository_summary)
        self.router.register("platform.job.status", self._job_status)
        self.router.register("platform.job.transition", self._job_transition)
        self.system.start()
        create_database()

    def _authorize(self, frame: ByteFrame) -> None:
        signature = frame.headers.get(_SIGNATURE_HEADER, "")
        nonce = frame.headers.get(_NONCE_HEADER, "")
        expires_raw = frame.headers.get(_EXPIRES_HEADER, "0")
        try:
            expires = int(expires_raw)
        except ValueError as exc:
            raise PermissionError("invalid byte-frame expiry") from exc
        if not signature or not nonce or expires <= int(time.time()):
            raise PermissionError("expired or unsigned byte-frame")
        expected = hmac.new(
            self._secret,
            _canonical_signature_input(frame),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise PermissionError("invalid byte-frame signature")
        with self._lock:
            if nonce in self._seen:
                raise PermissionError("replayed byte-frame")
            self._seen.add(nonce)
            self._seen_order.append(nonce)
            while len(self._seen_order) > self._replay_cache_size:
                self._seen.discard(self._seen_order.popleft())

    def execute(self, frame: ByteFrame) -> ByteFrame:
        self._authorize(frame)
        return self.system.execute_sync(frame)

    def frame(
        self,
        route: str,
        payload: dict[str, Any],
        *,
        ttl_seconds: int = 60,
    ) -> ByteFrame:
        return signed_frame(
            route,
            payload,
            secret=self._secret,
            ttl_seconds=ttl_seconds,
        )

    def _health(self, _frame: ByteFrame) -> dict[str, Any]:
        return {
            "status": "ok",
            "database": "shared",
            "system": self.system.status(),
        }

    def _repository_summary(self, frame: ByteFrame) -> dict[str, Any]:
        repository_id = int(frame.json()["repository_id"])
        with session_scope() as session:
            repository = session.get(Repository, repository_id)
            if repository is None:
                raise LookupError("repository not found")
            return {
                "repository_id": repository.id,
                "name": repository.name,
                "default_branch": repository.default_branch,
                "pull_requests": len(repository.pull_requests),
                "ci_pipelines": len(repository.ci_pipelines),
                "autonomous_jobs": len(repository.autonomous_jobs),
            }

    def _job_status(self, frame: ByteFrame) -> dict[str, Any]:
        task_id = str(frame.json()["task_id"])
        with session_scope() as session:
            job = session.scalar(
                select(AutonomousJob).where(AutonomousJob.task_id == task_id)
            )
            if job is None:
                raise LookupError("autonomous job not found")
            return {
                "task_id": job.task_id,
                "repository_id": job.repository_id,
                "status": job.status.value,
                "ci_pipeline_id": job.ci_pipeline_id,
                "result_summary": job.result_summary,
            }

    def _job_transition(self, frame: ByteFrame) -> dict[str, Any]:
        payload = frame.json()
        task_id = str(payload["task_id"])
        requested_status = AutonomousJobStatus(str(payload["status"]))
        summary = str(payload.get("result_summary") or "")[:20_000] or None
        verification_id = str(payload.get("verification_id") or "")[:100] or None
        with session_scope() as session:
            job = session.scalar(
                select(AutonomousJob).where(AutonomousJob.task_id == task_id)
            )
            if job is None:
                raise LookupError("autonomous job not found")
            if requested_status not in _ALLOWED_JOB_TRANSITIONS[job.status]:
                raise ValueError(
                    f"invalid job transition: {job.status.value} -> "
                    f"{requested_status.value}"
                )
            if requested_status is AutonomousJobStatus.PASSED and not verification_id:
                raise ValueError("passed jobs require a verification_id")
            job.status = requested_status
            job.result_summary = summary
            pipeline: CIPipeline | None = job.ci_pipeline
            if pipeline is not None:
                if requested_status in {
                    AutonomousJobStatus.INSPECTING,
                    AutonomousJobStatus.REPAIRING,
                    AutonomousJobStatus.VERIFYING,
                }:
                    pipeline.status = CIStatus.RUNNING
                elif requested_status is AutonomousJobStatus.PASSED:
                    pipeline.status = CIStatus.PASSED
                    pipeline.verification_id = verification_id
                    pipeline.completed_at = datetime.datetime.now(
                        datetime.timezone.utc
                    )
                elif requested_status in {
                    AutonomousJobStatus.FAILED,
                    AutonomousJobStatus.CANCELLED,
                }:
                    pipeline.status = CIStatus.FAILED
                    pipeline.completed_at = datetime.datetime.now(
                        datetime.timezone.utc
                    )
                if summary:
                    pipeline.execution_logs = summary
            return {
                "task_id": job.task_id,
                "status": job.status.value,
                "ci_status": pipeline.status.value if pipeline else None,
                "verification_id": pipeline.verification_id if pipeline else None,
            }


def platform_bus_from_environment() -> PlatformByteBus | None:
    """Return the internal bus when a secret is configured; otherwise stay disabled."""
    value = os.getenv("AMOSCLAUD_BYTE_BUS_SECRET", "").strip()
    return PlatformByteBus(value.encode("utf-8")) if value else None

"""The Amosclaud Model Station agent loop.

Responsibilities:

* probe the local inference backend and heartbeat the truth about it;
* claim queued inference requests from the model network;
* run them on the local backend and always report an outcome;
* survive transient network and server failures without dying.

Nothing here logs the station token, prompts or replies. Lengths and
identifiers are logged instead, because the payloads are user data.
"""

from __future__ import annotations

import platform
import signal
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable

from station import AGENT_NAME, __version__
from station.backend import BackendError, OllamaBackend, ProbeResult
from station.client import InferenceRequest, PlatformClient
from station.config import StationConfig
from station.logs import get_logger
from station.transport import HttpError, TransportError

IDLE = "idle"
HANDLED = "handled"
NOT_READY = "not_ready"
ERROR = "error"

MAX_COMPLETION_ATTEMPTS = 3


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _system_facts() -> dict[str, Any]:
    return {
        "os": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "hostname": platform.node(),
    }


class StationAgent:
    """Runs the outbound loop for one registered station."""

    def __init__(
        self,
        config: StationConfig,
        *,
        backend: OllamaBackend | None = None,
        client: PlatformClient | None = None,
        logger=None,
    ) -> None:
        self.config = config
        self.backend = backend or OllamaBackend(
            config.backend_url,
            config.model,
            chat_timeout=config.inference_timeout,
            probe_timeout=config.probe_timeout,
        )
        self.client = client or PlatformClient(config)
        self.log = logger or get_logger()
        self.stop_event = threading.Event()
        self.version = f"{AGENT_NAME}/{__version__}"[:50]
        self._probe_lock = threading.Lock()
        self._probe: ProbeResult = ProbeResult(False, "not probed yet")
        self._backoff = config.poll_interval
        self.heartbeats = 0
        self.completed = 0
        self.failed = 0

    # ------------------------------------------------------------- heartbeat
    @property
    def last_probe(self) -> ProbeResult:
        with self._probe_lock:
            return self._probe

    def probe_backend(self) -> ProbeResult:
        """Probe the backend, never raising: a failure means ``ready=False``."""
        try:
            probe = self.backend.probe()
        except Exception as error:  # pragma: no cover - backend.probe is defensive
            probe = ProbeResult(False, f"probe failed: {type(error).__name__}")
        with self._probe_lock:
            previous = self._probe
            self._probe = probe
        if previous.ready != probe.ready or previous.detail != probe.detail:
            self.log.info(
                "backend readiness changed: ready=%s detail=%s", probe.ready, probe.detail
            )
        return probe

    def heartbeat_payload(self, probe: ProbeResult) -> dict[str, Any]:
        """Build the exact body sent to the heartbeat endpoint."""
        system = _system_facts()
        system["agent"] = {"name": AGENT_NAME, "version": __version__}
        system["model"] = {
            "ready": bool(probe.ready),
            "name": self.config.model,
            "backend": "ollama",
            "backend_url": self.config.backend_url,
            "detail": probe.detail,
            "checked_at": _now(),
        }
        return {
            "version": self.version,
            "capabilities": list(self.config.capabilities),
            "system": system,
        }

    def heartbeat_once(self, probe: ProbeResult | None = None) -> bool:
        """Send one heartbeat. Returns ``True`` when the platform accepted it."""
        probe = self.probe_backend() if probe is None else probe
        payload = self.heartbeat_payload(probe)
        try:
            self.client.heartbeat(
                payload["version"], payload["capabilities"], payload["system"]
            )
        except HttpError as error:
            self.log.warning("heartbeat rejected: %s", error)
            return False
        except TransportError as error:
            self.log.warning("heartbeat could not be delivered: %s", error)
            return False
        except Exception as error:  # never kill the process on a heartbeat
            self.log.warning("heartbeat failed: %s: %s", type(error).__name__, error)
            return False
        self.heartbeats += 1
        self.log.debug(
            "heartbeat accepted station=%s ready=%s", self.config.station_id, probe.ready
        )
        return True

    def _heartbeat_loop(self) -> None:
        while not self.stop_event.is_set():
            if self.stop_event.wait(self.config.heartbeat_interval):
                return
            self.heartbeat_once()

    # ------------------------------------------------------------------ work
    def poll_once(self) -> str:
        """Claim at most one request and run it. Returns the loop outcome."""
        if not self.last_probe.ready:
            return NOT_READY
        try:
            request = self.client.claim()
        except HttpError as error:
            self.log.warning("claim rejected: %s", error)
            return ERROR
        except TransportError as error:
            self.log.warning("claim could not be delivered: %s", error)
            return ERROR
        except Exception as error:
            self.log.warning("claim failed: %s: %s", type(error).__name__, error)
            return ERROR
        if request is None:
            return IDLE
        self.handle(request)
        return HANDLED

    def handle(self, request: InferenceRequest) -> None:
        """Run one claimed request locally and always report the outcome."""
        self.log.info(
            "claimed request=%s messages=%d prompt_chars=%d requested_model=%s",
            request.id,
            len(request.messages),
            request.prompt_characters,
            request.model,
        )
        started = time.monotonic()
        runtime = f"ollama:{self.config.model}"
        try:
            reply = self.backend.chat(
                request.messages,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
            )
        except BackendError as error:
            self._report_failure(request, str(error), runtime)
            return
        except Exception as error:
            self._report_failure(request, f"{type(error).__name__}: {error}", runtime)
            return
        elapsed = time.monotonic() - started
        if not reply.strip():
            # The platform rejects a completed status without a reply (422).
            self._report_failure(request, "backend returned an empty reply", runtime)
            return
        self.log.info(
            "inference finished request=%s reply_chars=%d seconds=%.2f",
            request.id,
            len(reply),
            elapsed,
        )
        if self._complete(request.id, status="completed", reply=reply, runtime=runtime):
            self.completed += 1

    def _report_failure(self, request: InferenceRequest, error: str, runtime: str) -> None:
        short = error.replace("\n", " ")[:200]
        self.log.error("inference failed request=%s error=%s", request.id, short)
        if self._complete(request.id, status="failed", reply=None, runtime=runtime, error=short):
            self.failed += 1

    def _complete(
        self,
        request_id: str,
        *,
        status: str,
        reply: str | None,
        runtime: str,
        error: str | None = None,
    ) -> bool:
        """Report an outcome, retrying transient failures a few times."""
        for attempt in range(1, MAX_COMPLETION_ATTEMPTS + 1):
            try:
                self.client.complete(
                    request_id, status=status, reply=reply, runtime=runtime, error=error
                )
                self.log.info("reported request=%s status=%s", request_id, status)
                return True
            except HttpError as failure:
                self.log.error(
                    "completion rejected request=%s status=%s: %s",
                    request_id,
                    status,
                    failure,
                )
                if failure.status < 500:
                    return False
            except TransportError as failure:
                self.log.warning(
                    "completion attempt %d/%d failed request=%s: %s",
                    attempt,
                    MAX_COMPLETION_ATTEMPTS,
                    request_id,
                    failure,
                )
            except Exception as failure:
                self.log.warning(
                    "completion attempt %d/%d failed request=%s: %s: %s",
                    attempt,
                    MAX_COMPLETION_ATTEMPTS,
                    request_id,
                    type(failure).__name__,
                    failure,
                )
            if attempt < MAX_COMPLETION_ATTEMPTS and not self.stop_event.wait(
                min(2.0 * attempt, self.config.poll_max_interval)
            ):
                continue
            break
        self.log.error("gave up reporting request=%s status=%s", request_id, status)
        return False

    # ------------------------------------------------------------------ loop
    def next_interval(self, outcome: str) -> float:
        """Short interval while there is work, exponential backoff when idle."""
        if outcome == HANDLED:
            self._backoff = self.config.poll_interval
            return 0.0
        if outcome == IDLE:
            interval = min(self._backoff * 1.5, self.config.poll_max_interval)
        else:
            interval = min(max(self._backoff, self.config.poll_interval) * 2.0,
                           self.config.poll_max_interval)
        self._backoff = max(self.config.poll_interval, interval)
        return self._backoff

    def install_signal_handlers(self) -> None:
        def _handle(signum, _frame):  # pragma: no cover - exercised by real signals
            self.log.info("received signal %s, shutting down", signum)
            self.stop_event.set()

        for name in ("SIGINT", "SIGTERM"):
            handler = getattr(signal, name, None)
            if handler is None:
                continue
            try:
                signal.signal(handler, _handle)
            except (ValueError, OSError):  # not the main thread
                self.log.debug("cannot install %s handler outside the main thread", name)

    def run(self, *, handle_signals: bool = True, max_cycles: int | None = None) -> int:
        """Run until stopped. Returns the number of completed poll cycles."""
        if handle_signals:
            self.install_signal_handlers()
        self.log.info("station agent starting %s", self.config.summary())
        probe = self.probe_backend()
        if not probe.ready:
            self.log.warning(
                "backend is not ready at startup: %s (heartbeating as degraded)",
                probe.detail,
            )
        self.heartbeat_once(probe)
        heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop, name="station-heartbeat", daemon=True
        )
        heartbeat_thread.start()
        cycles = 0
        try:
            while not self.stop_event.is_set():
                if max_cycles is not None and cycles >= max_cycles:
                    break
                outcome = self.poll_once()
                cycles += 1
                if outcome == NOT_READY:
                    # Re-probe between polls so the station recovers as soon as
                    # the backend comes back, without waiting for a heartbeat.
                    self.log.debug("backend not ready, skipping claim")
                    self.probe_backend()
                    interval = min(self.config.poll_max_interval,
                                   max(self.config.poll_interval, 1.0))
                else:
                    interval = self.next_interval(outcome)
                if interval and self.stop_event.wait(interval):
                    break
        finally:
            self.stop_event.set()
            heartbeat_thread.join(timeout=5)
            self.log.info(
                "station agent stopped cycles=%d completed=%d failed=%d heartbeats=%d",
                cycles,
                self.completed,
                self.failed,
                self.heartbeats,
            )
        return cycles

    def stop(self) -> None:
        self.stop_event.set()


def build_agent(
    config: StationConfig | None = None, *, logger=None
) -> StationAgent:
    return StationAgent(config or StationConfig.from_env(), logger=logger)


__all__ = [
    "StationAgent",
    "build_agent",
    "IDLE",
    "HANDLED",
    "ERROR",
    "NOT_READY",
]


# Kept for callers that want a plain callable entry point.
Runner = Callable[[], int]

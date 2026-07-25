"""Ollama-compatible inference backend used by the Amosclaud station agent."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from station.transport import HttpError, TransportError, request_json


class BackendError(RuntimeError):
    """Local inference could not produce a reply."""


def _canonical(name: str) -> str:
    """Ollama reports ``model`` and ``model:latest`` for the same weights."""
    value = (name or "").strip()
    return value if ":" in value else f"{value}:latest"


@dataclass(frozen=True)
class ProbeResult:
    """Outcome of a readiness probe against the backend."""

    ready: bool
    detail: str
    models: tuple[str, ...] = field(default=())

    def as_dict(self) -> dict[str, Any]:
        return {"ready": self.ready, "detail": self.detail}


class OllamaBackend:
    """Talks to an Ollama-compatible HTTP server (``/api/tags``, ``/api/chat``)."""

    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        chat_timeout: float = 120.0,
        probe_timeout: float = 10.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.chat_timeout = chat_timeout
        self.probe_timeout = probe_timeout

    # ------------------------------------------------------------------ probe
    def probe(self) -> ProbeResult:
        """Confirm the backend answers and actually serves the wanted model.

        The result drives ``system.model.ready`` in the heartbeat, so it must
        never be optimistic: any failure reports ``ready=False``.
        """
        try:
            payload = request_json(
                f"{self.base_url}/api/tags", timeout=self.probe_timeout
            )
        except HttpError as error:
            return ProbeResult(False, f"backend returned {error.status}")
        except TransportError as error:
            return ProbeResult(False, f"backend unreachable: {error}")
        models = tuple(self._model_names(payload))
        if not models:
            return ProbeResult(False, "backend reported no installed models", models)
        if _canonical(self.model) not in {_canonical(name) for name in models}:
            return ProbeResult(False, f"model {self.model} is not installed", models)
        return ProbeResult(True, f"model {self.model} is installed", models)

    @staticmethod
    def _model_names(payload: Any) -> Iterable[str]:
        entries = payload.get("models") if isinstance(payload, Mapping) else None
        for entry in entries or []:
            if isinstance(entry, Mapping):
                name = entry.get("name") or entry.get("model")
                if isinstance(name, str) and name.strip():
                    yield name.strip()
            elif isinstance(entry, str) and entry.strip():
                yield entry.strip()

    # -------------------------------------------------------------- inference
    def chat(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        model: str | None = None,
    ) -> str:
        """Run one non-streaming chat completion and return the reply text."""
        clean = self._clean_messages(messages)
        if not clean:
            raise BackendError("no messages to run")
        name = model or self.model
        options = self._options(temperature, max_tokens)
        body: dict[str, Any] = {"model": name, "messages": clean, "stream": False}
        if options:
            body["options"] = options
        try:
            payload = self._post("/api/chat", body)
        except HttpError as error:
            if error.status not in {404, 405, 501}:
                raise BackendError(f"backend chat failed: {error}") from None
            payload = self._generate(clean, name, options)
        reply = self._reply_text(payload)
        if not reply:
            raise BackendError("backend returned an empty reply")
        return reply

    def _generate(
        self, messages: Sequence[Mapping[str, Any]], model: str, options: dict[str, Any]
    ) -> Any:
        """Fallback for backends that only expose the older /api/generate route."""
        body: dict[str, Any] = {
            "model": model,
            "prompt": self._flatten(messages),
            "stream": False,
        }
        if options:
            body["options"] = options
        try:
            return self._post("/api/generate", body)
        except HttpError as error:
            raise BackendError(f"backend generate failed: {error}") from None

    def _post(self, path: str, body: Mapping[str, Any]) -> Any:
        try:
            return request_json(
                f"{self.base_url}{path}",
                method="POST",
                payload=body,
                timeout=self.chat_timeout,
            )
        except TransportError as error:
            raise BackendError(f"backend unreachable: {error}") from None

    @staticmethod
    def _options(temperature: float | None, max_tokens: int | None) -> dict[str, Any]:
        options: dict[str, Any] = {}
        if temperature is not None:
            try:
                options["temperature"] = float(temperature)
            except (TypeError, ValueError):
                pass
        if max_tokens is not None:
            try:
                tokens = int(max_tokens)
            except (TypeError, ValueError):
                tokens = 0
            if tokens > 0:
                options["num_predict"] = tokens
        return options

    @staticmethod
    def _clean_messages(messages: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
        cleaned: list[dict[str, str]] = []
        for message in messages or []:
            if not isinstance(message, Mapping):
                continue
            role = str(message.get("role") or "user").strip() or "user"
            content = message.get("content")
            if content is None:
                continue
            cleaned.append({"role": role, "content": str(content)})
        return cleaned

    @staticmethod
    def _flatten(messages: Sequence[Mapping[str, Any]]) -> str:
        lines = [f"{message['role']}: {message['content']}" for message in messages]
        lines.append("assistant:")
        return "\n\n".join(lines)

    @staticmethod
    def _reply_text(payload: Any) -> str:
        if not isinstance(payload, Mapping):
            return ""
        message = payload.get("message")
        if isinstance(message, Mapping) and isinstance(message.get("content"), str):
            return message["content"].strip()
        response = payload.get("response")
        if isinstance(response, str):
            return response.strip()
        return ""

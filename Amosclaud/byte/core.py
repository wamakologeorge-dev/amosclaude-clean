"""Binary-safe message frame used by every Amosclaud byte component."""

from __future__ import annotations

import base64
import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any


class ByteFrameError(ValueError):
    """Raised when a frame is malformed or fails its integrity check."""


@dataclass(frozen=True, slots=True)
class ByteFrame:
    route: str
    payload: bytes
    frame_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_ns: int = field(default_factory=time.time_ns)
    headers: dict[str, str] = field(default_factory=dict)
    version: int = 1

    def __post_init__(self) -> None:
        invalid_route = (
            not self.route
            or len(self.route) > 200
            or any(char.isspace() for char in self.route)
        )
        if invalid_route:
            raise ByteFrameError("route must be non-empty, whitespace-free, and at most 200 chars")
        if not isinstance(self.payload, bytes):
            raise ByteFrameError("payload must be bytes")
        if len(self.payload) > 64 * 1024 * 1024:
            raise ByteFrameError("payload exceeds the 64 MiB frame limit")
        if self.version != 1:
            raise ByteFrameError(f"unsupported frame version: {self.version}")
        valid_headers = all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in self.headers.items()
        )
        if not valid_headers:
            raise ByteFrameError("headers must contain string keys and values")

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.payload).hexdigest()

    @classmethod
    def from_text(cls, route: str, text: str, **kwargs: Any) -> "ByteFrame":
        return cls(route=route, payload=text.encode("utf-8"), **kwargs)

    @classmethod
    def from_json(cls, route: str, value: Any, **kwargs: Any) -> "ByteFrame":
        encoded = json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
        headers = {"content-type": "application/json", **kwargs.pop("headers", {})}
        return cls(route=route, payload=encoded, headers=headers, **kwargs)

    def text(self) -> str:
        return self.payload.decode("utf-8")

    def json(self) -> Any:
        return json.loads(self.payload)

    def to_bytes(self) -> bytes:
        envelope = {
            "version": self.version,
            "frame_id": self.frame_id,
            "route": self.route,
            "created_ns": self.created_ns,
            "headers": self.headers,
            "payload": base64.b64encode(self.payload).decode("ascii"),
            "sha256": self.sha256,
        }
        return json.dumps(envelope, separators=(",", ":"), sort_keys=True).encode("utf-8")

    @classmethod
    def from_bytes(cls, raw: bytes) -> "ByteFrame":
        try:
            envelope = json.loads(raw)
            payload = base64.b64decode(envelope["payload"], validate=True)
            expected = str(envelope["sha256"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ByteFrameError("invalid byte-frame envelope") from exc
        if not hashlib.sha256(payload).hexdigest() == expected:
            raise ByteFrameError("byte-frame checksum mismatch")
        try:
            return cls(
                route=str(envelope["route"]),
                payload=payload,
                frame_id=str(envelope["frame_id"]),
                created_ns=int(envelope["created_ns"]),
                headers=dict(envelope.get("headers", {})),
                version=int(envelope["version"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ByteFrameError("invalid byte-frame fields") from exc

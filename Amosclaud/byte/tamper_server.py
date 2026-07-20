"""Tamper-aware byte server with evidence-only quarantine records."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import struct
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .core import ByteFrame, ByteFrameError
from .system import ByteSystem

_HEADER = struct.Struct("!I")
_MAX_WIRE_BYTES = 70 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class TamperEvidence:
    evidence_id: str
    observed_at_ns: int
    source: str
    packet_sha256: str
    packet_size: int
    failure: str
    detail: str


class TamperEvidenceStore:
    """Append-only JSONL evidence store that never persists packet contents."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def record(self, raw: bytes, source: str, error: Exception) -> TamperEvidence:
        evidence = TamperEvidence(
            evidence_id=uuid.uuid4().hex,
            observed_at_ns=time.time_ns(),
            source=source[:200],
            packet_sha256=hashlib.sha256(raw).hexdigest(),
            packet_size=len(raw),
            failure=type(error).__name__,
            detail=" ".join(str(error).split())[:300],
        )
        line = json.dumps(asdict(evidence), separators=(",", ":"), sort_keys=True) + "\n"
        with self._lock:
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(line)
                stream.flush()
                os.fsync(stream.fileno())
        return evidence

    def events(self, limit: int = 100) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        limit = max(1, min(limit, 1000))
        with self._lock:
            lines = self.path.read_text(encoding="utf-8").splitlines()[-limit:]
        return [json.loads(line) for line in reversed(lines) if line.strip()]


class TamperedDataServer:
    """One-frame-per-connection TCP server that quarantines invalid wire data."""

    def __init__(
        self,
        system: ByteSystem,
        evidence_store: TamperEvidenceStore,
        host: str = "127.0.0.1",
        port: int = 0,
        *,
        request_timeout: float = 30.0,
    ) -> None:
        self.system = system
        self.evidence_store = evidence_store
        self.host = host
        self.port = port
        self.request_timeout = request_timeout
        self.accepted = 0
        self.quarantined = 0
        self._server: asyncio.Server | None = None

    async def start(self) -> "TamperedDataServer":
        self.system.start()
        self._server = await asyncio.start_server(self._handle, self.host, self.port)
        self.port = int(self._server.sockets[0].getsockname()[1])
        return self

    async def close(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        self.system.stop()

    async def serve_forever(self) -> None:
        if self._server is None:
            await self.start()
        if self._server is None:
            raise RuntimeError("tampered-data server failed to start")
        async with self._server:
            await self._server.serve_forever()

    async def _packet(self, reader: asyncio.StreamReader) -> bytes:
        header = await asyncio.wait_for(reader.readexactly(_HEADER.size), self.request_timeout)
        length = _HEADER.unpack(header)[0]
        if length < 1 or length > _MAX_WIRE_BYTES:
            raise ByteFrameError("tampered packet length rejected")
        return await asyncio.wait_for(reader.readexactly(length), self.request_timeout)

    @staticmethod
    async def _send(writer: asyncio.StreamWriter, frame: ByteFrame) -> None:
        payload = frame.to_bytes()
        writer.write(_HEADER.pack(len(payload)) + payload)
        await writer.drain()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        source = str(peer[0] if isinstance(peer, tuple) and peer else "unknown")
        raw = b""
        try:
            raw = await self._packet(reader)
            frame = ByteFrame.from_bytes(raw)
            response = await asyncio.wait_for(
                self.system.execute(frame),
                timeout=self.request_timeout,
            )
            self.accepted += 1
            await self._send(writer, response)
        except (ByteFrameError, UnicodeError, json.JSONDecodeError) as error:
            evidence = self.evidence_store.record(raw, source, error)
            self.quarantined += 1
            await self._send(
                writer,
                ByteFrame.from_json(
                    "security.tamper.rejected",
                    {
                        "status": "rejected",
                        "reason": "integrity_check_failed",
                        "evidence_id": evidence.evidence_id,
                    },
                ),
            )
        except (asyncio.IncompleteReadError, asyncio.TimeoutError) as error:
            evidence = self.evidence_store.record(raw, source, error)
            self.quarantined += 1
            try:
                await self._send(
                    writer,
                    ByteFrame.from_json(
                        "security.tamper.rejected",
                        {"status": "rejected", "evidence_id": evidence.evidence_id},
                    ),
                )
            except ConnectionError:
                pass
        finally:
            writer.close()
            await writer.wait_closed()

    def status(self) -> dict[str, Any]:
        return {
            "service": "amosclaud-tampered-data-server",
            "running": self._server is not None,
            "host": self.host,
            "port": self.port,
            "accepted": self.accepted,
            "quarantined": self.quarantined,
            "evidence_path": str(self.evidence_store.path),
        }

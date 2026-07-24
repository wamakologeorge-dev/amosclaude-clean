"""Length-prefixed asyncio TCP server and client for Amosclaud byte frames."""

from __future__ import annotations

import asyncio
import struct

from .core import ByteFrame, ByteFrameError
from .system import ByteSystem

_HEADER = struct.Struct("!I")
_MAX_WIRE_BYTES = 70 * 1024 * 1024


async def _read_packet(reader: asyncio.StreamReader) -> bytes:
    length = _HEADER.unpack(await reader.readexactly(_HEADER.size))[0]
    if length < 1 or length > _MAX_WIRE_BYTES:
        raise ByteFrameError("invalid byte-server packet length")
    return await reader.readexactly(length)


async def _write_packet(writer: asyncio.StreamWriter, data: bytes) -> None:
    if len(data) > _MAX_WIRE_BYTES:
        raise ByteFrameError("byte-server response exceeds wire limit")
    writer.write(_HEADER.pack(len(data)) + data)
    await writer.drain()


class ByteServer:
    def __init__(
        self,
        system: ByteSystem,
        host: str = "127.0.0.1",
        port: int = 0,
        *,
        request_timeout: float = 30.0,
    ) -> None:
        self.system = system
        self.host = host
        self.port = port
        self.request_timeout = request_timeout
        self._server: asyncio.Server | None = None

    async def start(self) -> "ByteServer":
        self.system.start()
        self._server = await asyncio.start_server(self._handle, self.host, self.port)
        socket = self._server.sockets[0]
        self.port = int(socket.getsockname()[1])
        return self

    async def close(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        self.system.stop()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            raw = await asyncio.wait_for(_read_packet(reader), timeout=self.request_timeout)
            response = await asyncio.wait_for(
                self.system.execute(ByteFrame.from_bytes(raw)),
                timeout=self.request_timeout,
            )
            await _write_packet(writer, response.to_bytes())
        except Exception as exc:
            error = ByteFrame.from_json(
                "system.error",
                {"error": type(exc).__name__, "detail": str(exc)[:300]},
            )
            try:
                await _write_packet(writer, error.to_bytes())
            except (ConnectionError, ByteFrameError):
                pass
        finally:
            writer.close()
            await writer.wait_closed()


class ByteClient:
    def __init__(self, host: str, port: int, *, timeout: float = 30.0) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout

    async def request(self, frame: ByteFrame) -> ByteFrame:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(self.host, self.port),
            timeout=self.timeout,
        )
        try:
            await _write_packet(writer, frame.to_bytes())
            raw = await asyncio.wait_for(_read_packet(reader), timeout=self.timeout)
            return ByteFrame.from_bytes(raw)
        finally:
            writer.close()
            await writer.wait_closed()

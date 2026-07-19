"""Validated binary packet support for ``amosclaud.byte.cb``."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

MAGIC = b"AMCB1"


@dataclass(frozen=True)
class ByteCB:
    payload: bytes
    checksum: str

    @classmethod
    def from_value(cls, value: Any) -> "ByteCB":
        payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return cls(payload=payload, checksum=hashlib.sha256(payload).hexdigest())

    def verify(self) -> bool:
        return hashlib.sha256(self.payload).hexdigest() == self.checksum


def encode_packet(value: Any) -> bytes:
    packet = ByteCB.from_value(value)
    checksum = packet.checksum.encode("ascii")
    size = len(packet.payload).to_bytes(8, "big")
    return MAGIC + size + checksum + packet.payload


def decode_packet(packet: bytes) -> Any:
    if not packet.startswith(MAGIC) or len(packet) < len(MAGIC) + 8 + 64:
        raise ValueError("invalid Amosclaud CB packet")
    offset = len(MAGIC)
    size = int.from_bytes(packet[offset : offset + 8], "big")
    offset += 8
    checksum = packet[offset : offset + 64].decode("ascii")
    payload = packet[offset + 64 :]
    if len(payload) != size:
        raise ValueError("Amosclaud CB packet size mismatch")
    decoded = ByteCB(payload=payload, checksum=checksum)
    if not decoded.verify():
        raise ValueError("Amosclaud CB packet checksum mismatch")
    return json.loads(payload.decode("utf-8"))

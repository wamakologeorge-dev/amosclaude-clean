"""Useful binary operations shared by byte routes and bundle builders."""

from __future__ import annotations

import gzip
import hashlib
import hmac
from collections.abc import Iterable


def checksum(data: bytes, algorithm: str = "sha256") -> str:
    try:
        digest = hashlib.new(algorithm)
    except ValueError as exc:
        raise ValueError(f"unsupported checksum algorithm: {algorithm}") from exc
    digest.update(data)
    return digest.hexdigest()


def verify(data: bytes, expected: str, algorithm: str = "sha256") -> bool:
    return hmac.compare_digest(checksum(data, algorithm), expected.lower())


def chunk(data: bytes, size: int = 1024 * 1024) -> tuple[bytes, ...]:
    if size < 1:
        raise ValueError("chunk size must be positive")
    return tuple(data[index : index + size] for index in range(0, len(data), size))


def merge(chunks: Iterable[bytes], *, expected_sha256: str | None = None) -> bytes:
    data = b"".join(chunks)
    if expected_sha256 and not verify(data, expected_sha256):
        raise ValueError("merged byte checksum mismatch")
    return data


def compress(data: bytes, level: int = 6) -> bytes:
    if not 0 <= level <= 9:
        raise ValueError("compression level must be between 0 and 9")
    return gzip.compress(data, compresslevel=level, mtime=0)


def decompress(data: bytes, *, max_output_bytes: int = 64 * 1024 * 1024) -> bytes:
    result = gzip.decompress(data)
    if len(result) > max_output_bytes:
        raise ValueError("decompressed data exceeds configured limit")
    return result

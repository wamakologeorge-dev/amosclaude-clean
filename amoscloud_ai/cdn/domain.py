"""Framework-free domain models for the Amosclaud edge cache."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from types import MappingProxyType
from typing import Mapping
from urllib.parse import unquote

_ALLOWED_EXTENSIONS = frozenset(
    {
        ".avif",
        ".css",
        ".gif",
        ".ico",
        ".jpeg",
        ".jpg",
        ".js",
        ".json",
        ".map",
        ".mjs",
        ".png",
        ".svg",
        ".txt",
        ".wasm",
        ".webp",
        ".woff",
        ".woff2",
        ".xml",
    }
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class CacheDisposition(str, Enum):
    HIT = "hit"
    MISS = "miss"
    BYPASS = "bypass"


class CDNError(RuntimeError):
    """Base exception for edge-cache failures."""


class CDNConfigurationError(CDNError):
    """Raised when the edge service is not configured safely."""


class OriginNotFoundError(CDNError):
    """Raised when the configured origin does not contain an asset."""


class OriginFetchError(CDNError):
    """Raised when the configured origin cannot be read safely."""


@dataclass(frozen=True, slots=True)
class AssetRequest:
    path: str
    extension: str

    @classmethod
    def create(cls, path: str) -> "AssetRequest":
        candidate = str(path or "").strip()
        if not candidate or len(candidate) > 1_024:
            raise ValueError("asset path must contain between 1 and 1024 characters")
        if any(ord(character) < 32 for character in candidate):
            raise ValueError("asset path contains forbidden control characters")

        decoded = candidate
        for _ in range(3):
            next_value = unquote(decoded)
            if next_value == decoded:
                break
            decoded = next_value
        decoded = decoded.replace("\\", "/")
        if decoded.startswith("/") or "//" in decoded:
            raise ValueError("asset path must be relative and normalized")

        parts = decoded.split("/")
        if any(part in {"", ".", ".."} for part in parts):
            raise ValueError("asset path traversal is not allowed")
        if any(":" in part for part in parts):
            raise ValueError("asset path contains a forbidden separator")

        filename = parts[-1]
        dot = filename.rfind(".")
        extension = filename[dot:].lower() if dot >= 0 else ""
        if extension not in _ALLOWED_EXTENSIONS:
            raise ValueError("only allowlisted static asset types may use the CDN")
        return cls(path="/".join(parts), extension=extension)

    @property
    def cache_key(self) -> str:
        digest = hashlib.sha256(self.path.encode("utf-8")).hexdigest()
        return f"amosclaud:cdn:v1:{digest}"


@dataclass(frozen=True, slots=True)
class OriginAsset:
    body: bytes
    content_type: str
    ttl_seconds: int | None = None
    cacheable: bool = True
    headers: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))

    @classmethod
    def create(
        cls,
        *,
        body: bytes,
        content_type: str,
        ttl_seconds: int | None = None,
        cacheable: bool = True,
        headers: Mapping[str, str] | None = None,
    ) -> "OriginAsset":
        payload = bytes(body)
        media_type = str(content_type or "application/octet-stream").split(";", 1)[0].strip()
        if not media_type:
            media_type = "application/octet-stream"
        return cls(
            body=payload,
            content_type=media_type[:200],
            ttl_seconds=ttl_seconds,
            cacheable=bool(cacheable),
            headers=MappingProxyType(dict(headers or {})),
        )


@dataclass(frozen=True, slots=True)
class CacheEntry:
    body: bytes
    content_type: str
    etag: str
    stored_at: datetime
    expires_at: datetime
    headers: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))

    @classmethod
    def from_origin(
        cls,
        asset: OriginAsset,
        *,
        ttl_seconds: int,
        stored_at: datetime | None = None,
    ) -> "CacheEntry":
        observed = stored_at or utc_now()
        ttl = max(1, int(ttl_seconds))
        etag = '"' + hashlib.sha256(asset.body).hexdigest() + '"'
        return cls(
            body=asset.body,
            content_type=asset.content_type,
            etag=etag,
            stored_at=observed,
            expires_at=observed + timedelta(seconds=ttl),
            headers=asset.headers,
        )

    def is_expired(self, now: datetime | None = None) -> bool:
        return self.expires_at <= (now or utc_now())

    def age_seconds(self, now: datetime | None = None) -> int:
        delta = (now or utc_now()) - self.stored_at
        return max(0, int(delta.total_seconds()))

    def remaining_ttl(self, now: datetime | None = None) -> int:
        delta = self.expires_at - (now or utc_now())
        return max(0, int(delta.total_seconds()))


@dataclass(frozen=True, slots=True)
class EdgeResult:
    entry: CacheEntry
    disposition: CacheDisposition
    latency_ms: float

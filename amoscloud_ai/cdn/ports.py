"""Application-facing ports for CDN infrastructure adapters."""

from __future__ import annotations

from typing import Protocol, Sequence

from .domain import AssetRequest, CacheDisposition, CacheEntry, OriginAsset


class EdgeCache(Protocol):
    name: str

    def get(self, key: str) -> CacheEntry | None: ...

    def set(self, key: str, entry: CacheEntry) -> None: ...

    def purge(self, keys: Sequence[str]) -> int: ...


class OriginFetcher(Protocol):
    def fetch(self, request: AssetRequest) -> OriginAsset: ...


class EdgeTelemetry(Protocol):
    def record_request(
        self,
        *,
        disposition: CacheDisposition,
        extension: str,
        latency_ms: float,
        response_bytes: int,
        outcome: str,
    ) -> None: ...

    def record_purge(self, *, requested: int, purged: int) -> None: ...

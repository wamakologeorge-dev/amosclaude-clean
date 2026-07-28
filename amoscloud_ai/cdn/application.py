"""CDN use cases independent of FastAPI, Redis, and HTTP clients."""

from __future__ import annotations

import time
from typing import Sequence

from .domain import AssetRequest, CacheDisposition, CacheEntry, EdgeResult, utc_now
from .ports import EdgeCache, EdgeTelemetry, OriginFetcher


class CDNService:
    def __init__(
        self,
        cache: EdgeCache,
        origin: OriginFetcher,
        telemetry: EdgeTelemetry,
        *,
        default_ttl_seconds: int = 300,
        maximum_ttl_seconds: int = 86_400,
    ) -> None:
        self.cache = cache
        self.origin = origin
        self.telemetry = telemetry
        self.default_ttl_seconds = max(1, int(default_ttl_seconds))
        self.maximum_ttl_seconds = max(self.default_ttl_seconds, int(maximum_ttl_seconds))

    def get_asset(self, path: str) -> EdgeResult:
        requested = AssetRequest.create(path)
        started = time.monotonic()
        cached = self.cache.get(requested.cache_key)
        if cached is not None and not cached.is_expired():
            latency_ms = (time.monotonic() - started) * 1_000
            self.telemetry.record_request(
                disposition=CacheDisposition.HIT,
                extension=requested.extension,
                latency_ms=latency_ms,
                response_bytes=len(cached.body),
                outcome="success",
            )
            return EdgeResult(cached, CacheDisposition.HIT, latency_ms)

        try:
            origin_asset = self.origin.fetch(requested)
        except Exception:
            latency_ms = (time.monotonic() - started) * 1_000
            self.telemetry.record_request(
                disposition=CacheDisposition.MISS,
                extension=requested.extension,
                latency_ms=latency_ms,
                response_bytes=0,
                outcome="error",
            )
            raise

        requested_ttl = (
            origin_asset.ttl_seconds
            if origin_asset.ttl_seconds is not None
            else self.default_ttl_seconds
        )
        ttl_seconds = max(1, min(int(requested_ttl), self.maximum_ttl_seconds))
        entry = CacheEntry.from_origin(
            origin_asset,
            ttl_seconds=ttl_seconds,
            stored_at=utc_now(),
        )
        disposition = CacheDisposition.MISS
        if origin_asset.cacheable:
            self.cache.set(requested.cache_key, entry)
        else:
            disposition = CacheDisposition.BYPASS

        latency_ms = (time.monotonic() - started) * 1_000
        self.telemetry.record_request(
            disposition=disposition,
            extension=requested.extension,
            latency_ms=latency_ms,
            response_bytes=len(entry.body),
            outcome="success",
        )
        return EdgeResult(entry, disposition, latency_ms)

    def purge(self, paths: Sequence[str]) -> int:
        keys = [AssetRequest.create(path).cache_key for path in paths]
        purged = self.cache.purge(keys)
        self.telemetry.record_purge(requested=len(keys), purged=purged)
        return purged

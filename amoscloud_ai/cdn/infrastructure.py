"""Concrete cache, origin-fetch, and telemetry adapters for the Amosclaud CDN."""

from __future__ import annotations

import json
import os
import re
import threading
from collections import OrderedDict
from datetime import datetime
from typing import Sequence
from urllib.parse import quote, urlsplit

import httpx

from amosclaud_metrics.registry import registry as prometheus_registry

from .domain import (
    AssetRequest,
    CDNConfigurationError,
    CacheDisposition,
    CacheEntry,
    OriginAsset,
    OriginFetchError,
    OriginNotFoundError,
)

_CACHE_CONTROL_MAX_AGE = re.compile(r"(?:^|,)\s*(?:s-maxage|max-age)=(\d+)\s*(?:,|$)")


class MemoryEdgeCache:
    name = "memory"

    def __init__(self, *, maximum_entries: int = 2_000, maximum_bytes: int = 128 * 1024 * 1024):
        self.maximum_entries = max(1, int(maximum_entries))
        self.maximum_bytes = max(1, int(maximum_bytes))
        self._entries: OrderedDict[str, CacheEntry] = OrderedDict()
        self._bytes = 0
        self._lock = threading.Lock()

    def get(self, key: str) -> CacheEntry | None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            if entry.is_expired():
                self._remove(key)
                return None
            self._entries.move_to_end(key)
            return entry

    def set(self, key: str, entry: CacheEntry) -> None:
        size = len(entry.body)
        if size > self.maximum_bytes:
            return
        with self._lock:
            self._remove(key)
            self._entries[key] = entry
            self._bytes += size
            while self._entries and (
                len(self._entries) > self.maximum_entries or self._bytes > self.maximum_bytes
            ):
                oldest_key = next(iter(self._entries))
                self._remove(oldest_key)

    def purge(self, keys: Sequence[str]) -> int:
        purged = 0
        with self._lock:
            for key in dict.fromkeys(keys):
                if key in self._entries:
                    self._remove(key)
                    purged += 1
        return purged

    def _remove(self, key: str) -> None:
        entry = self._entries.pop(key, None)
        if entry is not None:
            self._bytes -= len(entry.body)


class RedisEdgeCache:
    name = "redis"

    def __init__(self, redis_url: str, *, key_prefix: str = "amosclaud:cdn:entry:") -> None:
        try:
            import redis
        except ImportError as exc:
            raise CDNConfigurationError("Redis CDN cache requires the redis package") from exc
        self._client = redis.Redis.from_url(redis_url, decode_responses=False)
        self._prefix = key_prefix

    def _key(self, key: str) -> str:
        return f"{self._prefix}{key.rsplit(':', 1)[-1]}"

    def get(self, key: str) -> CacheEntry | None:
        values = self._client.hgetall(self._key(key))
        if not values:
            return None
        try:
            entry = CacheEntry(
                body=bytes(values[b"body"]),
                content_type=values[b"content_type"].decode("utf-8"),
                etag=values[b"etag"].decode("utf-8"),
                stored_at=datetime.fromisoformat(values[b"stored_at"].decode("utf-8")),
                expires_at=datetime.fromisoformat(values[b"expires_at"].decode("utf-8")),
                headers=json.loads(values.get(b"headers", b"{}").decode("utf-8")),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            self._client.delete(self._key(key))
            return None
        if entry.is_expired():
            self._client.delete(self._key(key))
            return None
        return entry

    def set(self, key: str, entry: CacheEntry) -> None:
        ttl = entry.remaining_ttl()
        if ttl <= 0:
            return
        redis_key = self._key(key)
        self._client.hset(
            redis_key,
            mapping={
                "body": entry.body,
                "content_type": entry.content_type,
                "etag": entry.etag,
                "stored_at": entry.stored_at.isoformat(),
                "expires_at": entry.expires_at.isoformat(),
                "headers": json.dumps(dict(entry.headers), sort_keys=True, separators=(",", ":")),
            },
        )
        self._client.expire(redis_key, ttl)

    def purge(self, keys: Sequence[str]) -> int:
        redis_keys = [self._key(key) for key in dict.fromkeys(keys)]
        if not redis_keys:
            return 0
        return int(self._client.delete(*redis_keys))


class HTTPOriginFetcher:
    def __init__(
        self,
        origin_url: str,
        *,
        timeout_seconds: float = 10.0,
        maximum_asset_bytes: int = 25 * 1024 * 1024,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        parsed = urlsplit(str(origin_url or "").strip())
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise CDNConfigurationError("AMOSCLAUD_CDN_ORIGIN_URL must be an HTTP(S) origin")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise CDNConfigurationError(
                "CDN origin must not contain credentials, query, or fragment"
            )
        self.origin_url = origin_url.rstrip("/")
        self.maximum_asset_bytes = max(1, int(maximum_asset_bytes))
        self._client = httpx.Client(
            timeout=max(0.5, float(timeout_seconds)),
            follow_redirects=False,
            transport=transport,
            headers={"Accept-Encoding": "identity", "User-Agent": "amosclaud-edge/1"},
        )

    def fetch(self, request: AssetRequest) -> OriginAsset:
        target = f"{self.origin_url}/{quote(request.path, safe='/@._-~')}"
        with self._client.stream("GET", target) as response:
            if response.status_code == 404:
                raise OriginNotFoundError("asset was not found on the configured origin")
            if 300 <= response.status_code < 400:
                raise OriginFetchError("origin redirects are not followed by the edge service")
            if response.status_code != 200:
                raise OriginFetchError(f"origin returned HTTP {response.status_code}")

            declared = response.headers.get("content-length")
            if declared:
                try:
                    if int(declared) > self.maximum_asset_bytes:
                        raise OriginFetchError("origin asset exceeds the configured size limit")
                except ValueError as exc:
                    raise OriginFetchError("origin returned an invalid Content-Length") from exc

            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_bytes():
                total += len(chunk)
                if total > self.maximum_asset_bytes:
                    raise OriginFetchError("origin asset exceeds the configured size limit")
                chunks.append(chunk)

            content_type = response.headers.get("content-type", "application/octet-stream")
            if content_type.lower().startswith("text/html"):
                raise OriginFetchError("dynamic HTML responses are not accepted as CDN assets")
            cache_control = response.headers.get("cache-control", "")
            lowered = cache_control.lower()
            cacheable = "no-store" not in lowered and "private" not in lowered
            ttl_seconds = None
            match = _CACHE_CONTROL_MAX_AGE.search(lowered)
            if match:
                ttl_seconds = int(match.group(1))
            headers = {
                key: value[:500]
                for key, value in {
                    "Content-Language": response.headers.get("content-language", ""),
                }.items()
                if value
            }
            return OriginAsset.create(
                body=b"".join(chunks),
                content_type=content_type,
                ttl_seconds=ttl_seconds,
                cacheable=cacheable,
                headers=headers,
            )


class PrometheusEdgeTelemetry:
    def __init__(self) -> None:
        self._hits = 0
        self._requests = 0
        self._lock = threading.Lock()

    def record_request(
        self,
        *,
        disposition: CacheDisposition,
        extension: str,
        latency_ms: float,
        response_bytes: int,
        outcome: str,
    ) -> None:
        labels = {
            "cache": disposition.value,
            "extension": extension.lstrip("."),
            "outcome": outcome,
        }
        prometheus_registry.counter(
            "amosclaud_cdn_requests_total",
            help_text="Requests handled by the Amosclaud edge cache",
            labels=labels,
        )
        prometheus_registry.counter(
            "amosclaud_cdn_response_bytes_total",
            amount=response_bytes,
            help_text="Bytes returned by the Amosclaud edge cache",
            labels={"cache": disposition.value},
        )
        prometheus_registry.gauge(
            "amosclaud_cdn_edge_latency_ms",
            latency_ms,
            help_text="Latest Amosclaud edge request latency in milliseconds",
            labels={"cache": disposition.value, "outcome": outcome},
        )
        with self._lock:
            self._requests += 1
            if disposition is CacheDisposition.HIT:
                self._hits += 1
            ratio = self._hits / self._requests if self._requests else 0.0
        prometheus_registry.gauge(
            "amosclaud_cdn_cache_hit_ratio",
            ratio,
            help_text="In-process Amosclaud CDN cache hit ratio",
        )

    def record_purge(self, *, requested: int, purged: int) -> None:
        prometheus_registry.counter(
            "amosclaud_cdn_purge_requests_total",
            help_text="Administrative Amosclaud CDN purge operations",
        )
        prometheus_registry.counter(
            "amosclaud_cdn_purged_entries_total",
            amount=purged,
            help_text="Amosclaud CDN cache entries removed",
        )
        prometheus_registry.gauge(
            "amosclaud_cdn_last_purge_requested_entries",
            requested,
            help_text="Entries requested by the latest Amosclaud CDN purge",
        )


def build_cache_backend():
    backend = os.getenv("AMOSCLAUD_CDN_CACHE_BACKEND", "auto").strip().lower()
    redis_url = os.getenv("REDIS_URL", "").strip()
    if backend not in {"auto", "memory", "redis"}:
        raise CDNConfigurationError("AMOSCLAUD_CDN_CACHE_BACKEND must be auto, memory, or redis")
    if backend == "redis" or (backend == "auto" and redis_url):
        if not redis_url:
            raise CDNConfigurationError("REDIS_URL is required for the Redis CDN cache")
        return RedisEdgeCache(redis_url)
    return MemoryEdgeCache(
        maximum_entries=int(os.getenv("AMOSCLAUD_CDN_MEMORY_MAX_ENTRIES", "2000")),
        maximum_bytes=int(os.getenv("AMOSCLAUD_CDN_MEMORY_MAX_BYTES", str(128 * 1024 * 1024))),
    )

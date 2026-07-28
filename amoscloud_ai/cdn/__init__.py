"""Security-bounded edge caching for static Amosclaud assets."""

from .application import CDNService
from .domain import (
    AssetRequest,
    CDNConfigurationError,
    CDNError,
    CacheDisposition,
    CacheEntry,
    EdgeResult,
    OriginAsset,
    OriginFetchError,
    OriginNotFoundError,
)
from .infrastructure import (
    HTTPOriginFetcher,
    MemoryEdgeCache,
    PrometheusEdgeTelemetry,
    RedisEdgeCache,
    build_cache_backend,
)

__all__ = [
    "AssetRequest",
    "CDNConfigurationError",
    "CDNError",
    "CDNService",
    "CacheDisposition",
    "CacheEntry",
    "EdgeResult",
    "HTTPOriginFetcher",
    "MemoryEdgeCache",
    "OriginAsset",
    "OriginFetchError",
    "OriginNotFoundError",
    "PrometheusEdgeTelemetry",
    "RedisEdgeCache",
    "build_cache_backend",
]

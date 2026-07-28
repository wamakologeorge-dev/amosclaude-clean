from __future__ import annotations

import gzip

import httpx
import pytest

from amoscloud_ai.cdn import (
    AssetRequest,
    CDNConfigurationError,
    CDNService,
    CacheDisposition,
    HTTPOriginFetcher,
    MemoryEdgeCache,
    OriginAsset,
    OriginFetchError,
)


class FakeOrigin:
    def __init__(self, body: bytes = b"console.log('edge')") -> None:
        self.body = body
        self.calls = 0

    def fetch(self, request: AssetRequest) -> OriginAsset:
        self.calls += 1
        return OriginAsset.create(
            body=self.body,
            content_type="application/javascript",
            ttl_seconds=60,
        )


class CapturingTelemetry:
    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []
        self.purges: list[tuple[int, int]] = []

    def record_request(self, **values) -> None:
        self.requests.append(values)

    def record_purge(self, *, requested: int, purged: int) -> None:
        self.purges.append((requested, purged))


def build_service():
    cache = MemoryEdgeCache(maximum_entries=4, maximum_bytes=10_000)
    origin = FakeOrigin()
    telemetry = CapturingTelemetry()
    return CDNService(cache, origin, telemetry), origin, telemetry


@pytest.mark.parametrize(
    "path",
    [
        "../secrets.env",
        "%2e%2e/%2e%2e/etc/passwd.js",
        "/absolute/app.js",
        "assets\\..\\secret.js",
        "index.html",
        "api/users",
    ],
)
def test_asset_path_rejects_traversal_and_dynamic_content(path: str) -> None:
    with pytest.raises(ValueError):
        AssetRequest.create(path)


def test_service_caches_static_assets_and_reports_hit_ratio_inputs() -> None:
    service, origin, telemetry = build_service()

    first = service.get_asset("static/app.js")
    second = service.get_asset("static/app.js")

    assert first.disposition is CacheDisposition.MISS
    assert second.disposition is CacheDisposition.HIT
    assert first.entry.body == second.entry.body
    assert first.entry.etag == second.entry.etag
    assert origin.calls == 1
    assert [item["disposition"] for item in telemetry.requests] == [
        CacheDisposition.MISS,
        CacheDisposition.HIT,
    ]


def test_exact_purge_forces_the_next_request_back_to_origin() -> None:
    service, origin, telemetry = build_service()
    service.get_asset("static/app.js")

    assert service.purge(["static/app.js"]) == 1
    assert telemetry.purges == [(1, 1)]

    result = service.get_asset("static/app.js")
    assert result.disposition is CacheDisposition.MISS
    assert origin.calls == 2


def test_origin_fetcher_uses_fixed_origin_without_forwarding_credentials() -> None:
    observed = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["url"] = str(request.url)
        observed["authorization"] = request.headers.get("authorization")
        observed["cookie"] = request.headers.get("cookie")
        return httpx.Response(
            200,
            headers={
                "Content-Type": "text/css",
                "Cache-Control": "public, max-age=120",
            },
            content=b"body{}",
        )

    fetcher = HTTPOriginFetcher(
        "https://origin.example/static",
        transport=httpx.MockTransport(handler),
    )
    asset = fetcher.fetch(AssetRequest.create("styles/site.css"))

    assert observed["url"] == "https://origin.example/static/styles/site.css"
    assert observed["authorization"] is None
    assert observed["cookie"] is None
    assert asset.body == b"body{}"
    assert asset.ttl_seconds == 120


def test_origin_redirects_compression_and_credential_origins_are_rejected() -> None:
    with pytest.raises(CDNConfigurationError):
        HTTPOriginFetcher("https://user:password@origin.example")

    fetcher = HTTPOriginFetcher(
        "https://origin.example",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(302, headers={"Location": "http://127.0.0.1"})
        ),
    )
    with pytest.raises(OriginFetchError):
        fetcher.fetch(AssetRequest.create("assets/app.js"))

    compressed = HTTPOriginFetcher(
        "https://origin.example",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                headers={
                    "Content-Type": "application/javascript",
                    "Content-Encoding": "gzip",
                },
                content=gzip.compress(b"compressed"),
            )
        ),
    )
    with pytest.raises(OriginFetchError):
        compressed.fetch(AssetRequest.create("assets/app.js"))


def test_memory_cache_is_bounded_by_entry_count() -> None:
    service, origin, _ = build_service()
    service.cache.maximum_entries = 1

    service.get_asset("static/app.js")
    service.get_asset("static/other.js")
    service.get_asset("static/app.js")

    assert origin.calls == 3

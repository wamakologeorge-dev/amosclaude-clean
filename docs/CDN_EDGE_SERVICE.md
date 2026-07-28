# Amosclaud CDN Edge Service

The Amosclaud CDN is a software-defined static-asset edge cache. It can be deployed
in multiple cloud regions, but this repository does not claim to provide a global
physical network by itself.

## Security boundary

The edge route is intentionally not a general-purpose open proxy.

- The origin is fixed by `AMOSCLAUD_CDN_ORIGIN_URL`; clients cannot supply a URL.
- Only allowlisted static extensions are accepted. HTML and dynamic API paths are rejected.
- Encoded traversal, absolute paths, backslashes, control characters, and ambiguous paths fail closed.
- Origin redirects are never followed.
- Cookies, authorization headers, and browser credentials are never forwarded to the origin.
- Asset size, cache TTL, memory usage, and entry count are bounded.
- Purging requires an administrator session or a separate bearer token.

## API

```text
GET  /api/v1/cdn/assets/{asset_path}
POST /api/v1/cdn/purge
```

Example purge request:

```json
{
  "paths": ["static/app.js", "static/site.css"]
}
```

Use either an Amosclaud administrator session or:

```text
Authorization: Bearer <AMOSCLAUD_CDN_PURGE_TOKEN>
```

Purge operations are written to the existing monitoring audit store with the actor,
source address, requested count, and purged count. Raw credentials are never recorded.

## Cache backends

`AMOSCLAUD_CDN_CACHE_BACKEND=auto` uses Redis when `REDIS_URL` is configured and
otherwise uses a bounded in-process LRU cache. Set the value explicitly to `redis`
or `memory` when deterministic deployment behavior is required.

The local cache is useful for one node. Redis provides a shared cache for multiple
Uvicorn workers or regional replicas. Deploy one service per region behind a DNS or
load-balancing layer to create a multi-region edge network.

## Telemetry

The edge service exports:

- `amosclaud_cdn_requests_total`
- `amosclaud_cdn_response_bytes_total`
- `amosclaud_cdn_edge_latency_ms`
- `amosclaud_cdn_cache_hit_ratio`
- `amosclaud_cdn_purge_requests_total`
- `amosclaud_cdn_purged_entries_total`

Response headers include `X-Amosclaud-Cache`, `X-Amosclaud-Edge-Latency-Ms`, `ETag`,
and `Age` so deployments can verify cache behavior directly.

## TLS and edge deployment

Terminate public TLS at a hardened reverse proxy or managed cloud ingress. The Python
service retains Amosclaud's global security headers, origin checks, and request limits,
but certificate lifecycle management belongs at the deployment edge rather than in
application code.

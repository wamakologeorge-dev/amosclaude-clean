"""FastAPI interface adapter for the Amosclaud static-asset edge cache."""

from __future__ import annotations

import hmac
import os
from functools import lru_cache
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request, status
from fastapi.responses import Response
from pydantic import BaseModel, Field

from amoscloud_ai.api.routes.auth import get_user_from_session
from amoscloud_ai.cdn import (
    CDNConfigurationError,
    CDNService,
    HTTPOriginFetcher,
    OriginFetchError,
    OriginNotFoundError,
    PrometheusEdgeTelemetry,
    build_cache_backend,
)
from amoscloud_ai.monitoring import AuditOutcome

router = APIRouter(prefix="/cdn", tags=["cdn"])


class PurgeRequest(BaseModel):
    paths: list[str] = Field(min_length=1, max_length=100)


def _environment_integer(name: str, default: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise CDNConfigurationError(f"{name} must be an integer") from exc
    if value <= 0:
        raise CDNConfigurationError(f"{name} must be greater than zero")
    return value


def _environment_float(name: str, default: float) -> float:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = float(raw)
    except ValueError as exc:
        raise CDNConfigurationError(f"{name} must be a number") from exc
    if value <= 0:
        raise CDNConfigurationError(f"{name} must be greater than zero")
    return value


@lru_cache(maxsize=1)
def get_cdn_service() -> CDNService:
    origin_url = os.getenv("AMOSCLAUD_CDN_ORIGIN_URL", "").strip()
    if not origin_url:
        raise CDNConfigurationError("AMOSCLAUD_CDN_ORIGIN_URL is not configured")
    origin = HTTPOriginFetcher(
        origin_url,
        timeout_seconds=_environment_float("AMOSCLAUD_CDN_ORIGIN_TIMEOUT_SECONDS", 10.0),
        maximum_asset_bytes=_environment_integer(
            "AMOSCLAUD_CDN_MAX_ASSET_BYTES", 25 * 1024 * 1024
        ),
    )
    return CDNService(
        build_cache_backend(),
        origin,
        PrometheusEdgeTelemetry(),
        default_ttl_seconds=_environment_integer("AMOSCLAUD_CDN_DEFAULT_TTL_SECONDS", 300),
        maximum_ttl_seconds=_environment_integer("AMOSCLAUD_CDN_MAX_TTL_SECONDS", 86_400),
    )


def _purge_actor(request: Request, authorization: str | None) -> int | None:
    user = get_user_from_session(request.cookies.get("amos_session"))
    if user and bool(user["is_admin"]):
        return int(user["id"])

    expected = os.getenv("AMOSCLAUD_CDN_PURGE_TOKEN", "").strip()
    supplied = authorization or ""
    if expected and hmac.compare_digest(supplied, f"Bearer {expected}"):
        return None
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="CDN purge is not configured; use an administrator session",
        )
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid CDN credential")


def _response_headers(result) -> dict[str, str]:
    ttl = result.entry.remaining_ttl()
    cache_control = (
        "no-store"
        if result.disposition.value == "bypass"
        else (f"public, max-age={ttl}" if ttl else "no-store")
    )
    headers = {
        "ETag": result.entry.etag,
        "Age": str(result.entry.age_seconds()),
        "Cache-Control": cache_control,
        "X-Amosclaud-Cache": result.disposition.value.upper(),
        "X-Amosclaud-Edge-Latency-Ms": f"{result.latency_ms:.3f}",
        "X-Content-Type-Options": "nosniff",
    }
    headers.update(dict(result.entry.headers))
    return headers


@router.get(
    "/assets/{asset_path:path}",
    summary="Fetch an allowlisted static asset through the edge cache",
)
def fetch_asset(
    asset_path: str,
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
) -> Response:
    try:
        result = get_cdn_service().get_asset(asset_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except CDNConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except OriginNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except OriginFetchError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    headers = _response_headers(result)
    if if_none_match and hmac.compare_digest(if_none_match, result.entry.etag):
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)
    return Response(
        content=result.entry.body,
        media_type=result.entry.content_type,
        headers=headers,
    )


@router.post("/purge", summary="Purge exact static asset paths from the edge cache")
def purge_assets(
    body: PurgeRequest,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    actor_id = _purge_actor(request, authorization)
    try:
        purged = get_cdn_service().purge(body.paths)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except CDNConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    from amoscloud_ai.api.routes.monitoring import get_monitoring_service

    get_monitoring_service().record_audit(
        action="cdn.cache.purge",
        resource_type="cdn_cache",
        resource_id=None,
        outcome=AuditOutcome.ALLOWED,
        reason=f"Purged {purged} CDN cache entries",
        metadata={
            "requested_paths": len(body.paths),
            "purged_entries": purged,
            "source_ip": request.client.host if request.client else "unknown",
        },
        actor_id=actor_id,
    )
    return {"requested": len(body.paths), "purged": purged}

from __future__ import annotations

import hmac
import os
import time

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import PlainTextResponse

from amosclaud_metrics.registry import registry


def install_metrics(app: FastAPI) -> None:
    @app.middleware("http")
    async def observe_request(request: Request, call_next):
        started = time.monotonic()
        registry.gauge_add(
            "amosclaud_http_requests_in_flight", 1, help_text="Requests currently executing"
        )
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            route = request.scope.get("route")
            path = getattr(route, "path", "unmatched")
            labels = {"method": request.method, "route": path, "status": str(status)}
            registry.counter(
                "amosclaud_http_requests_total", help_text="Completed API requests", labels=labels
            )
            registry.counter(
                "amosclaud_http_request_duration_seconds_total",
                time.monotonic() - started,
                help_text="Cumulative API request duration",
                labels={"method": request.method, "route": path},
            )
            registry.gauge_add(
                "amosclaud_http_requests_in_flight", -1, help_text="Requests currently executing"
            )

    @app.get("/metrics", include_in_schema=False)
    def application_metrics(authorization: str | None = Header(default=None)) -> PlainTextResponse:
        expected = os.getenv("AMOSCLAUD_METRICS_TOKEN", "").strip()
        if expected and (
            not authorization or not hmac.compare_digest(authorization, f"Bearer {expected}")
        ):
            raise HTTPException(status_code=401, detail="Invalid metrics credential")
        return PlainTextResponse(registry.render(), media_type="text/plain; version=0.0.4")

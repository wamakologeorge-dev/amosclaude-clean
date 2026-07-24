"""Security controls shared by the Amosclaud web and native clients."""

from __future__ import annotations

import ipaddress
import os
import time
from collections import defaultdict, deque
from threading import Lock

import redis
from redis.exceptions import RedisError

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from amoscloud_ai.core.access import AccessMode, AccessPolicy


class SecurityMiddleware(BaseHTTPMiddleware):
    """Apply network policy, security headers, request limits, origin checks, and abuse protection."""

    _lock = Lock()
    _attempts: dict[str, deque[float]] = defaultdict(deque)

    def __init__(self, app):
        super().__init__(app)
        self.max_body_bytes = int(os.getenv("MAX_REQUEST_BODY_BYTES", str(2 * 1024 * 1024)))
        self.auth_window_seconds = int(os.getenv("AUTH_RATE_WINDOW_SECONDS", "300"))
        self.auth_max_attempts = int(os.getenv("AUTH_RATE_MAX_ATTEMPTS", "30"))
        self.signup_max_attempts = int(os.getenv("AUTH_SIGNUP_RATE_MAX_ATTEMPTS", "12"))
        self.auth_rate_namespace = os.getenv("AUTH_RATE_NAMESPACE", "v2").strip() or "v3"
        self.redis_url = os.getenv("REDIS_URL", "").strip()
        self.production = os.getenv("ENVIRONMENT", "development").lower() in {"production", "prod"}
        self.redis = redis.Redis.from_url(self.redis_url, decode_responses=True) if self.redis_url else None
        self.trust_proxy_headers = os.getenv("TRUST_PROXY_HEADERS", "false").strip().lower() in {
            "1", "true", "yes", "on",
        }
        self.trust_container_gateway = os.getenv(
            "AMOSCLAUD_TRUST_CONTAINER_GATEWAY", "false"
        ).strip().lower() in {"1", "true", "yes", "on"}
        configured = os.getenv(
            "TRUSTED_ORIGINS",
            "https://amosclaud.com,https://www.amosclaud.com,http://localhost,http://localhost:8000",
        )
        self.trusted_origins = {
            item.strip().rstrip("/") for item in configured.split(",") if item.strip()
        }
        approval_origins = os.getenv(
            "AMOSCLAUD_WEBSITE_ORIGINS",
            "https://wamakologeorge-dev.github.io",
        )
        self.approval_origins = {
            item.strip().rstrip("/") for item in approval_origins.split(",") if item.strip()
        }

    def _client_host(self, request: Request) -> str:
        if self.trust_proxy_headers:
            forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
            if forwarded:
                return forwarded
        return request.client.host if request.client else "unknown"

    def _network_allowed(self, policy: AccessPolicy, host: str) -> bool:
        if policy.allows_client(host):
            return True
        if policy.mode is not AccessMode.LOCAL or not self.trust_container_gateway:
            return False
        try:
            return ipaddress.ip_address(host).is_private
        except ValueError:
            return False

    def _client_key(self, request: Request) -> str:
        return f"{self._client_host(request)}:{request.url.path}"

    def _attempt_limit(self, path: str) -> int:
        if path in {
            "/api/v1/auth/register/request-code",
            "/api/v1/auth/register/verify",
            "/auth/register/request-code",
            "/auth/register/verify",
        }:
            return self.signup_max_attempts
        return self.auth_max_attempts

    def _rate_limited(self, request: Request) -> bool:
        sensitive = {
            "/api/v1/auth/login",
            "/api/v1/auth/register/request-code",
            "/api/v1/auth/register/verify",
            "/api/v1/auth/password/forgot",
            "/api/v1/auth/password/reset",
            "/auth/login",
            "/auth/register/request-code",
            "/auth/register/verify",
        }
        if request.method != "POST" or request.url.path not in sensitive:
            return False

        now = time.monotonic()
        cutoff = now - self.auth_window_seconds
        key = self._client_key(request)
        limit = self._attempt_limit(request.url.path)

        if self.redis:
            redis_key = f"amosclaud:rate:auth:{self.auth_rate_namespace}:{key}"
            try:
                count = self.redis.incr(redis_key)
                if count == 1:
                    self.redis.expire(redis_key, self.auth_window_seconds)
                return count > limit
            except RedisError:
                # Authentication must remain available during a Redis outage.
                # Fall back to the process-local limiter instead of treating every
                # real user as abusive and returning an immediate HTTP 429.
                pass

        with self._lock:
            bucket = self._attempts[key]
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= limit:
                return True
            bucket.append(now)
        return False

    def _trusted_request_origins(self, path: str) -> set[str]:
        if path.startswith("/api/v1/approvals/"):
            return self.trusted_origins | self.approval_origins
        return self.trusted_origins

    async def dispatch(self, request: Request, call_next):
        try:
            policy = AccessPolicy.from_environment()
        except ValueError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=503)

        client_host = self._client_host(request)
        if not self._network_allowed(policy, client_host):
            return JSONResponse(
                {
                    "detail": "This Amosclaud installation does not allow access from this network.",
                    "access_mode": policy.mode.value,
                },
                status_code=403,
            )

        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > self.max_body_bytes:
                    return JSONResponse({"detail": "Request body is too large"}, status_code=413)
            except ValueError:
                return JSONResponse({"detail": "Invalid Content-Length header"}, status_code=400)

        if self._rate_limited(request):
            return JSONResponse(
                {"detail": "Too many attempts for this action. Please wait a few minutes and try again."},
                status_code=429,
                headers={"Retry-After": str(self.auth_window_seconds)},
            )

        if request.method not in {"GET", "HEAD", "OPTIONS"} and request.cookies.get("amos_session"):
            origin = request.headers.get("origin")
            allowed_origins = self._trusted_request_origins(request.url.path)
            if origin and origin.rstrip("/") not in allowed_origins:
                return JSONResponse({"detail": "Untrusted request origin"}, status_code=403)

        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()"
        )
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data: https:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; connect-src 'self' https:; object-src 'none'; base-uri 'self'; "
            "frame-ancestors 'none'; form-action 'self'",
        )
        if request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https":
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        if request.url.path.startswith(("/api/", "/auth")) or request.url.path in {
            "/login", "/admin",
        }:
            response.headers.setdefault("Cache-Control", "no-store")
        return response

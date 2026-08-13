"""Canonical public-domain policy for the Amosclaud platform deployment.

The canonical platform domain is ``amosclauds.com`` (note the trailing "s").
It is the domain the live Railway deployment actually serves, with a valid
TLS certificate.

The legacy ``amosclaud.com`` apex and its ``www.amosclaud.com`` subdomain are
hosted by an unrelated third-party account. Any configuration still pointing
at those legacy hosts is normalised forward to the new canonical domain, so a
stale environment variable can never drag the platform, its authentication
cookies, or its OAuth callback back onto the old host. Custom self-hosted
domains remain supported and pass through untouched.
"""

from __future__ import annotations

import os
from urllib.parse import urlsplit

CANONICAL_PLATFORM_URL = "https://amosclauds.com"
LEGACY_HOSTS = {"amosclaud.com", "www.amosclaud.com"}
CANONICAL_HOSTS = {"amosclauds.com", "www.amosclauds.com"}
AMOSCLAUD_HOSTS = LEGACY_HOSTS | CANONICAL_HOSTS
GITHUB_CALLBACK_PATH = "/api/v1/auth/github/admin-callback"

# Backwards-compatible alias for modules/tests that still import the old name.
WWW_PLATFORM_URL = CANONICAL_PLATFORM_URL


def _normalise_public_url(value: str) -> str:
    candidate = value.strip()
    if not candidate:
        return CANONICAL_PLATFORM_URL
    if "://" not in candidate:
        candidate = f"https://{candidate}"
    parsed = urlsplit(candidate)
    hostname = (parsed.hostname or "").lower()
    if hostname in AMOSCLAUD_HOSTS:
        return CANONICAL_PLATFORM_URL
    return candidate.rstrip("/")


def enforce_platform_domain_policy() -> None:
    """Keep Amosclaud auth and GitHub connections on one public callback."""

    public_url = _normalise_public_url(os.getenv("AMOSCLAUD_PUBLIC_URL", ""))
    callback_url = f"{public_url}{GITHUB_CALLBACK_PATH}"

    os.environ["AMOSCLAUD_PUBLIC_URL"] = public_url
    os.environ["GITHUB_ADMIN_CALLBACK_URL"] = callback_url
    os.environ["GITHUB_REPOSITORY_CALLBACK_URL"] = callback_url

    public_host = (urlsplit(public_url).hostname or "").lower()
    if public_host in CANONICAL_HOSTS:
        # Host-only cookies prevent the unrelated legacy apex platform from
        # receiving Amosclaud sessions or OAuth state values.
        os.environ["AUTH_COOKIE_DOMAIN"] = ""

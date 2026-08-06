"""Canonical public-domain policy for the Amosclaud platform deployment.

The apex ``amosclaud.com`` hostname is hosted by a separate platform. The
Amosclaud application, its authentication cookies, and its OAuth callback must
stay on ``www.amosclaud.com``. Custom self-hosted domains remain supported.
"""

from __future__ import annotations

import os
from urllib.parse import urlsplit

WWW_PLATFORM_URL = "https://www.amosclaud.com"
AMOSCLAUD_HOSTS = {"amosclaud.com", "www.amosclaud.com"}
GITHUB_CALLBACK_PATH = "/api/v1/auth/github/admin-callback"


def _normalise_public_url(value: str) -> str:
    candidate = value.strip()
    if not candidate:
        return WWW_PLATFORM_URL
    if "://" not in candidate:
        candidate = f"https://{candidate}"
    parsed = urlsplit(candidate)
    hostname = (parsed.hostname or "").lower()
    if hostname in AMOSCLAUD_HOSTS:
        return WWW_PLATFORM_URL
    return candidate.rstrip("/")


def enforce_platform_domain_policy() -> None:
    """Keep Amosclaud auth and GitHub connections on one public callback."""

    public_url = _normalise_public_url(os.getenv("AMOSCLAUD_PUBLIC_URL", ""))
    callback_url = f"{public_url}{GITHUB_CALLBACK_PATH}"

    os.environ["AMOSCLAUD_PUBLIC_URL"] = public_url
    os.environ["GITHUB_ADMIN_CALLBACK_URL"] = callback_url
    os.environ["GITHUB_REPOSITORY_CALLBACK_URL"] = callback_url

    public_host = (urlsplit(public_url).hostname or "").lower()
    configured_cookie_domain = os.getenv("AUTH_COOKIE_DOMAIN", "").strip()
    cookie_host = configured_cookie_domain.lstrip(".").lower()
    if public_host == "www.amosclaud.com" and cookie_host == "amosclaud.com":
        # Host-only cookies prevent the unrelated apex platform from receiving
        # Amosclaud sessions or OAuth state values.
        os.environ["AUTH_COOKIE_DOMAIN"] = ""

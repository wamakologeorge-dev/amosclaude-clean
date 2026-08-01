"""Stable URL normalization helpers for Amosclaud runtime components."""

from __future__ import annotations

import os
from urllib.parse import urlsplit, urlunsplit

PUBLIC_HOSTS = {"amosclaud.com", "www.amosclaud.com"}
CANONICAL_PUBLIC_HOST = "www.amosclaud.com"
PUBLIC_URL_ENV_NAMES = (
    "AMOSCLAUD_API_URL",
    "AMOSCLAUD_PROVIDER_API_URL",
    "AMOSCLAUD_PUBLIC_URL",
    "AMOSCLAUD_URL",
)
DEFAULT_PUBLIC_URL = "https://www.amosclaud.com"
DEFAULT_ALLOWED_ORIGINS = "https://www.amosclaud.com,http://localhost:8000,http://127.0.0.1:8000"


def normalize_public_amosclaud_url(value: str | None) -> str:
    raw = str(value or "").strip()
    if not raw:
        return DEFAULT_PUBLIC_URL

    candidate = raw if "://" in raw else f"https://{raw}"
    parts = urlsplit(candidate)
    if (parts.hostname or "").lower() not in PUBLIC_HOSTS:
        return raw.rstrip("/")

    try:
        port = parts.port
    except ValueError:
        return raw.rstrip("/")

    netloc = CANONICAL_PUBLIC_HOST
    if port not in {None, 80, 443}:
        netloc = f"{netloc}:{port}"
    return urlunsplit(parts._replace(scheme="https", netloc=netloc)).rstrip("/")


def normalize_public_environment() -> None:
    for name in PUBLIC_URL_ENV_NAMES:
        value = os.environ.get(name)
        if value:
            os.environ[name] = normalize_public_amosclaud_url(value)

    origins = os.environ.get("AMOSCLAUD_ALLOWED_ORIGINS", "")
    if origins:
        os.environ["AMOSCLAUD_ALLOWED_ORIGINS"] = ",".join(
            (
                normalize_public_amosclaud_url(item)
                if (urlsplit(item.strip()).hostname or "").lower() in PUBLIC_HOSTS
                else item.strip().rstrip("/")
            )
            for item in origins.split(",")
            if item.strip()
        )
    else:
        os.environ["AMOSCLAUD_ALLOWED_ORIGINS"] = DEFAULT_ALLOWED_ORIGINS

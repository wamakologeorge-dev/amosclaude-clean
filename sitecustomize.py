"""Normalize configured Amosclaud public endpoints before application imports.

Python imports ``sitecustomize`` automatically during interpreter startup when
this repository is on ``sys.path``. Several independent Amosclaud entry points
historically accepted ``http://www.amosclaud.com``. An HTTP-to-HTTPS redirect can
rewrite a POST into GET, which produces FastAPI's ``405 Method Not Allowed``.

Only explicitly configured public Amosclaud domains are upgraded. Unset values,
localhost, loopback, Docker, Railway private-network, and other endpoints remain
untouched so this guard cannot silently configure a model provider.
"""

from __future__ import annotations

import os
from urllib.parse import urlsplit, urlunsplit

_PUBLIC_HOSTS = {"amosclaud.com", "www.amosclaud.com"}
_PUBLIC_URL_ENV_NAMES = (
    "AMOSCLAUD_API_URL",
    "AMOSCLAUD_PROVIDER_API_URL",
    "AMOSCLAUD_PUBLIC_URL",
    "AMOSCLAUD_URL",
)
_DEFAULT_PUBLIC_URL = "https://www.amosclaud.com"


def normalize_public_amosclaud_url(value: str | None) -> str:
    """Return a canonical HTTPS URL for Amosclaud's public domains only."""
    raw = str(value or "").strip()
    if not raw:
        return _DEFAULT_PUBLIC_URL

    candidate = raw if "://" in raw else f"https://{raw}"
    parts = urlsplit(candidate)
    if (parts.hostname or "").lower() not in _PUBLIC_HOSTS:
        return raw.rstrip("/")

    scheme = "https" if parts.scheme.lower() in {"", "http", "https"} else parts.scheme
    normalized = parts._replace(scheme=scheme, netloc=parts.netloc.lower())
    return urlunsplit(normalized).rstrip("/")


def normalize_public_environment() -> None:
    """Upgrade configured public URLs without inventing missing configuration."""
    for name in _PUBLIC_URL_ENV_NAMES:
        value = os.environ.get(name)
        if value:
            os.environ[name] = normalize_public_amosclaud_url(value)

    origins = os.environ.get("AMOSCLAUD_ALLOWED_ORIGINS", "")
    if origins:
        os.environ["AMOSCLAUD_ALLOWED_ORIGINS"] = ",".join(
            (
                normalize_public_amosclaud_url(item)
                if (urlsplit(item.strip()).hostname or "").lower() in _PUBLIC_HOSTS
                else item.strip().rstrip("/")
            )
            for item in origins.split(",")
            if item.strip()
        )


normalize_public_environment()

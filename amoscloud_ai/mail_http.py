"""HTTPS-based outbound mail transport for Amosclaud.

Railway (and several other hosts) block outbound SMTP ports (25/465/587),
which makes classic SMTP delivery impossible in production. This module
delivers mail over HTTPS (port 443) using the Resend API when
``RESEND_API_KEY`` is configured. Credentials remain environment-only and
are never written to logs or storage.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

RESEND_ENDPOINT = "https://api.resend.com/emails"


class HttpMailError(RuntimeError):
    """Raised when the HTTPS mail provider cannot deliver a message."""


def http_mail_configured() -> bool:
    """Return True when an HTTPS mail provider is configured."""
    return bool(os.getenv("RESEND_API_KEY", "").strip())


def deliver_via_http(sender: str, recipient: str, subject: str, body: str) -> None:
    """Deliver a plain-text email through the Resend HTTPS API.

    Raises HttpMailError when the provider is not configured or the
    delivery fails, so callers can fall back or surface a 503.
    """
    api_key = os.getenv("RESEND_API_KEY", "").strip()
    if not api_key:
        raise HttpMailError("HTTPS mail provider is not configured")

    payload = json.dumps(
        {
            "from": sender,
            "to": [recipient],
            "subject": subject,
            "text": body,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        RESEND_ENDPOINT,
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            if response.status >= 300:
                raise HttpMailError(f"HTTPS mail provider returned status {response.status}")
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")[:200]
        except Exception:  # noqa: BLE001 - best effort diagnostics only
            pass
        raise HttpMailError(f"HTTPS mail provider rejected the message ({exc.code}): {detail}") from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise HttpMailError("HTTPS mail provider is unreachable") from exc


__all__ = ["HttpMailError", "deliver_via_http", "http_mail_configured"]

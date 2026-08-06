"""HTTPS-based outbound mail transport for Amosclaud.

Railway and several other hosts can restrict outbound SMTP. This module sends
mail over HTTPS using the Resend API when ``RESEND_API_KEY`` is configured.
It also normalizes the documented Railway mail variable names so the primary
account router and the central mail sender always read the same configuration.
Credentials remain environment-only and are never written to logs or storage.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

RESEND_ENDPOINT = "https://api.resend.com/emails"


class HttpMailError(RuntimeError):
    """Raised when the HTTPS mail provider cannot deliver a message."""


def _copy_setting(target: str, *sources: str) -> None:
    """Populate a legacy setting only when an operator has not set it directly."""

    if os.getenv(target) is not None:
        return
    for source in sources:
        value = os.getenv(source)
        if value is not None and value.strip():
            os.environ[target] = value.strip()
            return


# The primary account router historically reads SMTP_* while newer Railway
# documentation uses MAIL_SMTP_* and AMOSCLAUD_SECURITY_FROM. Normalize once at
# import time so signup, sign-in codes, password reset, and Amos Mail agree.
_copy_setting("SMTP_HOST", "MAIL_SMTP_HOST")
_copy_setting("SMTP_PORT", "MAIL_SMTP_PORT")
_copy_setting("SMTP_USERNAME", "MAIL_SMTP_USERNAME")
_copy_setting("SMTP_PASSWORD", "MAIL_SMTP_PASSWORD")
_copy_setting("SMTP_TLS", "MAIL_SMTP_TLS")
_copy_setting(
    "SMTP_FROM",
    "AMOSCLAUD_SECURITY_FROM",
    "MAIL_SMTP_FROM",
    "RESEND_FROM",
)


def http_mail_configured() -> bool:
    """Return True when an HTTPS mail provider is configured."""

    return bool(os.getenv("RESEND_API_KEY", "").strip())


def deliver_via_http(sender: str, recipient: str, subject: str, body: str) -> None:
    """Deliver a plain-text email through the Resend HTTPS API."""

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
        raise HttpMailError(
            f"HTTPS mail provider rejected the message ({exc.code}): {detail}"
        ) from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise HttpMailError("HTTPS mail provider is unreachable") from exc


__all__ = ["HttpMailError", "deliver_via_http", "http_mail_configured"]

"""Bridge account verification routes to the central Amosclaud mail transport."""

from __future__ import annotations

from types import ModuleType
from typing import Callable

from fastapi import HTTPException

from amoscloud_ai.mail_delivery import MailDeliveryError, deliver_security_code

DELIVERY_UNAVAILABLE_DETAIL = (
    "Amosclaud email delivery is temporarily unavailable. "
    "Ask the administrator to verify the HTTPS email provider or SMTP settings, then try again."
)


def build_auth_code_sender(code_minutes: int) -> Callable[[str, str, str], None]:
    """Return a sender compatible with the account router's private hook."""

    minutes = max(1, int(code_minutes))

    def send_code(email: str, code: str, purpose: str) -> None:
        central_purpose = "password" if purpose == "reset" else purpose
        try:
            deliver_security_code(email, code, central_purpose, minutes=minutes)
        except MailDeliveryError as exc:
            raise HTTPException(status_code=503, detail=DELIVERY_UNAVAILABLE_DETAIL) from exc

    return send_code


def install_auth_mail_delivery(auth_module: ModuleType) -> None:
    """Install one mail implementation for signup, login, and recovery codes."""

    auth_module._send_code = build_auth_code_sender(auth_module.CODE_MINUTES)


__all__ = [
    "DELIVERY_UNAVAILABLE_DETAIL",
    "build_auth_code_sender",
    "install_auth_mail_delivery",
]

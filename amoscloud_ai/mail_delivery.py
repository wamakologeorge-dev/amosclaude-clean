"""Central outbound mail delivery for Amosclaud account security.

All authentication and recovery messages use an @amosclaud.com sender. SMTP
credentials remain environment-only and are never written to logs or storage.
"""
from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage


class MailDeliveryError(RuntimeError):
    """Raised when Amosclaud cannot deliver a security message."""


def _setting(primary: str, fallback: str | None = None, default: str = "") -> str:
    value = os.getenv(primary)
    if value is None and fallback:
        value = os.getenv(fallback)
    return (value if value is not None else default).strip()


def deliver_security_code(recipient: str, code: str, purpose: str, *, minutes: int = 15) -> None:
    """Deliver a one-time account-security code through Amosclaud SMTP."""
    host = _setting("MAIL_SMTP_HOST", "SMTP_HOST")
    if not host:
        raise MailDeliveryError("Amosclaud email delivery is not configured")

    port = int(_setting("MAIL_SMTP_PORT", "SMTP_PORT", "587"))
    username = _setting("MAIL_SMTP_USERNAME", "SMTP_USERNAME")
    password = _setting("MAIL_SMTP_PASSWORD", "SMTP_PASSWORD")
    use_tls = _setting("MAIL_SMTP_TLS", "SMTP_TLS", "true").lower() in {"1", "true", "yes", "on"}
    sender = _setting("AMOSCLAUD_SECURITY_FROM", "MAIL_SMTP_FROM", "no-reply@amosclaud.com")
    if not sender.lower().endswith("@amosclaud.com"):
        raise MailDeliveryError("AMOSCLAUD_SECURITY_FROM must use the @amosclaud.com domain")

    messages = {
        "recovery-email": ("Verify your Amosclaud recovery email", "verify your recovery email"),
        "username": ("Recover your Amosclaud username", "recover your Amosclaud username"),
        "password": ("Reset your Amosclaud password", "reset your Amosclaud password"),
        "register": ("Verify your Amosclaud account", "complete your Amosclaud account setup"),
        "login": ("Your Amosclaud sign-in code", "sign in to Amosclaud"),
    }
    subject, action = messages.get(purpose, ("Your Amosclaud security code", "continue securely"))

    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(
        f"Your Amosclaud verification code is {code}.\n\n"
        f"Use it within {minutes} minutes to {action}.\n"
        "Amosclaud staff will never ask you to send this code in chat or email.\n"
        "If you did not request this message, you can ignore it."
    )

    try:
        with smtplib.SMTP(host, port, timeout=20) as smtp:
            if use_tls:
                smtp.starttls()
            if username and password:
                smtp.login(username, password)
            smtp.send_message(message, from_addr=sender, to_addrs=[recipient])
    except (smtplib.SMTPException, OSError, ValueError) as exc:
        raise MailDeliveryError("Amosclaud could not deliver the security code") from exc


__all__ = ["MailDeliveryError", "deliver_security_code"]

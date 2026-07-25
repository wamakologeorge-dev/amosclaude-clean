"""Logging for the station agent, with hard redaction of station credentials."""

from __future__ import annotations

import logging
import sys
from typing import Iterable

LOGGER_NAME = "amosclaud.station"
REDACTED = "***redacted***"


def get_logger(name: str = LOGGER_NAME) -> logging.Logger:
    return logging.getLogger(name)


class SecretFilter(logging.Filter):
    """Replace known secrets anywhere in a formatted log record."""

    def __init__(self, secrets: Iterable[str] = ()) -> None:
        super().__init__()
        self._secrets: list[str] = []
        for secret in secrets:
            self.add(secret)

    def add(self, secret: str | None) -> None:
        value = (secret or "").strip()
        if len(value) >= 8 and value not in self._secrets:
            self._secrets.append(value)

    def scrub(self, text: str) -> str:
        for secret in self._secrets:
            if secret in text:
                text = text.replace(secret, REDACTED)
        return text

    def filter(self, record: logging.LogRecord) -> bool:
        if not self._secrets:
            return True
        try:
            message = record.getMessage()
        except Exception:  # pragma: no cover - defensive, bad % formatting
            return True
        scrubbed = self.scrub(message)
        if scrubbed != message:
            record.msg = scrubbed
            record.args = ()
        if record.exc_text:
            record.exc_text = self.scrub(record.exc_text)
        return True


class SecretFormatter(logging.Formatter):
    """Formatter that scrubs secrets from the fully rendered record.

    The filter above cannot see tracebacks, which are rendered during
    formatting, so the final string is scrubbed here as well.
    """

    def __init__(self, fmt: str, secret_filter: SecretFilter) -> None:
        super().__init__(fmt)
        self._secret_filter = secret_filter

    def format(self, record: logging.LogRecord) -> str:
        return self._secret_filter.scrub(super().format(record))


def configure_logging(
    level: str = "INFO",
    secrets: Iterable[str] = (),
    *,
    stream=None,
    logger_name: str = LOGGER_NAME,
) -> logging.Logger:
    """Install a single stderr handler that always scrubs the station token."""
    logger = logging.getLogger(logger_name)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    handler = logging.StreamHandler(stream if stream is not None else sys.stderr)
    secret_filter = SecretFilter(secrets)
    handler.setFormatter(
        SecretFormatter("%(asctime)s %(levelname)-7s %(name)s %(message)s", secret_filter)
    )
    handler.addFilter(secret_filter)
    logger.addFilter(secret_filter)
    logger.addHandler(handler)
    logger.setLevel(getattr(logging, str(level).upper(), logging.INFO))
    logger.propagate = False
    return logger

"""Logging configuration for Amoscloud AI"""

import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

log = logging.getLogger("amoscloud_ai")

_VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


def configure_log_level(level: str) -> None:
    """Set log level, falling back to INFO for invalid values."""
    resolved = level.upper() if level.upper() in _VALID_LOG_LEVELS else "INFO"
    log.setLevel(getattr(logging, resolved))

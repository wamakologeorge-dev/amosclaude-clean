"""Centralised logger for Amoscloud AI."""

import logging
import sys

from amoscloud_ai.config import settings


def _create_logger() -> logging.Logger:
    logger = logging.getLogger("amoscloud_ai")
    if logger.handlers:
        return logger

    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logger.setLevel(level)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.propagate = False
    return logger


log = _create_logger()

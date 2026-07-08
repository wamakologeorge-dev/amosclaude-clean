"""Worker entry point for Amoscloud AI"""

import logging
from src.amoscloud_ai.logger import log
from src.amoscloud_ai.config import settings


def main():
    log.setLevel(getattr(logging, settings.log_level, logging.INFO))
    log.info("Amoscloud AI worker starting up")
    log.info(f"Environment: {settings.environment}")


if __name__ == "__main__":
    main()

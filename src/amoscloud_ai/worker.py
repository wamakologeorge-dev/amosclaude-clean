"""Worker entry point for Amoscloud AI"""

from src.amoscloud_ai.logger import log, configure_log_level
from src.amoscloud_ai.config import settings


def main():
    configure_log_level(settings.log_level)
    log.info("Amoscloud AI worker starting up")
    log.info(f"Environment: {settings.environment}")


if __name__ == "__main__":
    main()

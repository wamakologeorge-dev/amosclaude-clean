"""
Background worker entry point (placeholder for async task processing).
Extend with Celery tasks or similar as the project grows.
"""

from src.amoscloud_ai.logger import log


def main() -> None:
    log.info("Amoscloud AI worker started (idle – no tasks configured yet).")


if __name__ == "__main__":
    main()

"""CLI entry point for Amoscloud AI"""

import sys
import logging

logger = logging.getLogger(__name__)


def main() -> None:
    """Main entry point for the Amoscloud AI CLI"""
    logging.basicConfig(level=logging.INFO)
    logger.info("Amoscloud AI started")
    print("Amoscloud AI - CI/CD & Deployment Automation System")
    print("Use --help for available commands.")


if __name__ == "__main__":
    main()

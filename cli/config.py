"""Configuration for the Amosclaud Autonomous command-line client."""

from __future__ import annotations

import os


class CLIConfig:
    API_URL = os.getenv("AMOSCLAUD_API_URL", "http://localhost:8000").rstrip("/")
    API_KEY = os.getenv("AMOSCLAUD_API_KEY", "")
    AGENT_ID = os.getenv("AMOSCLAUD_AGENT_ID", "amosclaud-autonomous")
    TIMEOUT = int(os.getenv("AMOSCLAUD_TIMEOUT", "30"))
    DEFAULT_BRANCH = os.getenv("AMOSCLAUD_DEFAULT_BRANCH", "main")
    REPOSITORY_ID = os.getenv("AMOSCLAUD_REPOSITORY_ID", "")

"""Configuration for the Amosclaud Autonomous command-line client."""

from __future__ import annotations

import os

from sitecustomize import normalize_public_amosclaud_url


class CLIConfig:
    API_URL = normalize_public_amosclaud_url(
        os.getenv("AMOSCLAUD_API_URL", "http://localhost:8000")
    )
    API_KEY = os.getenv("AMOSCLAUD_API_KEY", "")
    AGENT_ID = os.getenv("AMOSCLAUD_AGENT_ID", "amosclaud-autonomous")
    TIMEOUT = int(os.getenv("AMOSCLAUD_TIMEOUT", "30"))
    DEFAULT_BRANCH = os.getenv("AMOSCLAUD_DEFAULT_BRANCH", "main")
    REPOSITORY_ID = os.getenv("AMOSCLAUD_REPOSITORY_ID", "")

"""Configuration hook module for the api-gateway testing environment.

Provides isolated workspace mock engines for Amosclaud-ai and Amosclaud-fixee.
"""

import pytest
import pytest_asyncio
from httpx import AsyncClient

# Attempt to load your gateway application instance dynamically
try:
    from main import app
except ImportError:
    # Fallback to local gateway path context if called from repository root
    import sys
    import os
    sys.path.insert(0, os.path.dirname(__file__))
    from main import app


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    """
    Configures pytest to use the standard asyncio backend for handling
    concurrent gateway connections.
    """
    return "asyncio"


@pytest_asyncio.fixture
async def amosclaud_test_client():
    """
    Forces the testing environment to communicate strictly using JSON payloads.
    This eliminates downstream HTML engine page leaks ( مثل '<!doctype html>' ).
    """
    async with AsyncClient(
        app=app,
        base_url="http://testserver",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Amosclaud-Agent": "Amosclaud-ai",
            "X-Amosclaud-Fixer": "Amosclaud-fixee"
        }
    ) as client:
        yield client

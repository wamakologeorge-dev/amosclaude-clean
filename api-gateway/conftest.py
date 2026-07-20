"""Configuration hook module for the api-gateway testing environment.

Provides isolated workspace mock engines for Amosclaud-ai and Amosclaud-fixee.
"""

import pytest
import pytest_asyncio
import httpx
from httpx import AsyncClient

# Load the gateway application under a distinct module name. Importing it as
# ``main`` polluted sys.modules and shadowed the repository root entry point.
import importlib.util
from pathlib import Path

_gateway_spec = importlib.util.spec_from_file_location(
    "api_gateway_main", Path(__file__).with_name("main.py")
)
assert _gateway_spec and _gateway_spec.loader
_gateway_module = importlib.util.module_from_spec(_gateway_spec)
_gateway_spec.loader.exec_module(_gateway_module)
app = _gateway_module.app

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
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Amosclaud-Agent": "Amosclaud-ai",
            "X-Amosclaud-Fixer": "Amosclaud-fixee"
        }
    ) as client:
        yield client

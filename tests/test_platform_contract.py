import asyncio

import httpx

from amoscloud_ai.main import create_app


def request(path: str):
    async def run():
        transport = httpx.ASGITransport(app=create_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get(path)

    return asyncio.run(run())


def test_agent_discovery_and_openapi_contract_are_public():
    plugin = request("/.well-known/ai-plugin.json")
    assert plugin.status_code == 200
    assert plugin.json()["api"]["url"].endswith("/openapi.yaml")

    contract = request("/openapi.yaml")
    assert contract.status_code == 200
    assert "createVerifiedTask" in contract.text

"""HTTP client contracts for native Amosclaud MCP repository operations."""

from __future__ import annotations

import json

import httpx
import pytest

from amosclaud_mcp.client import AmosclaudClient, AmosclaudClientConfig, AmosclaudMCPError


def _client(handler) -> AmosclaudClient:
    return AmosclaudClient(
        AmosclaudClientConfig(
            base_url="https://amosclauds.com",
            autonomous_key="amos-token",
            timeout_seconds=5,
        ),
        transport=httpx.MockTransport(handler),
    )


def test_native_repository_reads_use_amosclaud_gateway_and_bearer() -> None:
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer amos-token"
        seen.append((request.method, request.url.path))
        if request.url.path.endswith("/repositories"):
            return httpx.Response(200, json=[{"id": 7, "name": "Amosclaud"}])
        if request.url.path.endswith("/repositories/7/tree"):
            assert request.url.params["branch"] == "main"
            return httpx.Response(200, json=[{"path": "README.md", "type": "file", "size": 12}])
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    with _client(handler) as client:
        repositories = client.list_repositories()
        tree = client.list_repository_tree(7)

    assert repositories == [{"id": 7, "name": "Amosclaud"}]
    assert tree[0]["path"] == "README.md"
    assert seen == [
        ("GET", "/api/v1/mcp-gateway/repositories"),
        ("GET", "/api/v1/mcp-gateway/repositories/7/tree"),
    ]


def test_native_repository_write_is_committed_through_amosclaud_gateway() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "PUT"
        assert request.url.path == "/api/v1/mcp-gateway/repositories/11/files"
        assert request.headers["authorization"] == "Bearer amos-token"
        payload = json.loads(request.content.decode("utf-8"))
        assert payload == {
            "path": "src/app.py",
            "content": "print('Amosclaud')\n",
            "branch": "feature/direct-mcp",
            "commit_message": "Write through Amosclaud",
        }
        return httpx.Response(
            200,
            json={
                "path": "src/app.py",
                "branch": "feature/direct-mcp",
                "commit": "a" * 40,
            },
        )

    with _client(handler) as client:
        result = client.write_repository_file(
            11,
            path="src/app.py",
            content="print('Amosclaud')\n",
            branch="feature/direct-mcp",
            commit_message="Write through Amosclaud",
        )

    assert result["commit"] == "a" * 40


def test_repository_id_validation_happens_before_network_call() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("network must not be called")

    with _client(handler) as client:
        with pytest.raises(AmosclaudMCPError, match="positive integer"):
            client.get_repository(0)

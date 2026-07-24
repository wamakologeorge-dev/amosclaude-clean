from __future__ import annotations

import json

import httpx
import pytest

from amosclaud_mcp.client import (
    AmosclaudClient,
    AmosclaudClientConfig,
    AmosclaudMCPError,
)


def test_config_reads_first_party_environment(monkeypatch):
    monkeypatch.setenv("AMOSCLAUD_API_URL", "https://www.amosclaud.com/")
    monkeypatch.setenv("AMOSCLAUD_AUTONOMOUS_KEY", "secret-key")
    monkeypatch.setenv("AMOSCLAUD_MCP_TIMEOUT", "30")

    config = AmosclaudClientConfig.from_environment()

    assert config.base_url == "https://www.amosclaud.com"
    assert config.autonomous_key == "secret-key"
    assert config.timeout_seconds == 30


def test_run_autonomous_sends_governed_repository_metadata():
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["authorization"] = request.headers.get("authorization")
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "accepted": True,
                "pipeline_id": "pipeline-1",
                "status": "pending",
                "reply": "Queued",
            },
        )

    config = AmosclaudClientConfig(
        base_url="https://amosclaud.test",
        autonomous_key="autonomous-key",
    )
    client = AmosclaudClient(config, transport=httpx.MockTransport(handler))
    try:
        result = client.run_autonomous(
            objective="Fix the failing tests and commit the verified repair.",
            mode="fix",
            branch="main",
            repository_id=42,
            apply_changes=True,
        )
    finally:
        client.close()

    assert result["pipeline_id"] == "pipeline-1"
    assert captured["path"] == "/api/v1/agent/run"
    assert captured["authorization"] == "Bearer autonomous-key"
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["metadata"]["source"] == "amosclaud-mcp"
    assert body["metadata"]["repository_id"] == 42
    assert body["metadata"]["use_agent"] is True
    assert body["metadata"]["apply_changes"] is True


def test_protected_tools_require_autonomous_key():
    client = AmosclaudClient(
        AmosclaudClientConfig(
            base_url="https://amosclaud.test",
            autonomous_key=None,
        ),
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(500, json={"detail": "should not be called"})
        ),
    )
    try:
        with pytest.raises(AmosclaudMCPError, match="AMOSCLAUD_AUTONOMOUS_KEY"):
            client.get_pipeline("pipeline-1")
    finally:
        client.close()


def test_api_errors_are_reported_without_exposing_key():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "Invalid autonomous key"})

    client = AmosclaudClient(
        AmosclaudClientConfig(
            base_url="https://amosclaud.test",
            autonomous_key="do-not-leak-this",
        ),
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(AmosclaudMCPError) as error:
            client.run_autonomous(objective="Inspect the repository.")
    finally:
        client.close()

    assert "Invalid autonomous key" in str(error.value)
    assert "do-not-leak-this" not in str(error.value)

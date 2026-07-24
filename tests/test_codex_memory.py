"""Tests for the codex memory layer and its autonomous-codex API."""
from __future__ import annotations

import asyncio

import httpx
import pytest

from amoscloud_ai import codex_memory
from amoscloud_ai.api.routes import autonomous_codex
from amoscloud_ai.main import create_app

app = create_app()


@pytest.fixture(autouse=True)
def _isolated_codex(tmp_path, monkeypatch):
    monkeypatch.setenv("AMOSCLAUD_CODEX_MEMORY_DIR", str(tmp_path / "codex"))
    codex_memory.reset_cache_for_tests()
    yield
    codex_memory.reset_cache_for_tests()


def request(method: str, path: str, **kwargs):
    async def _go():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(_go())


def test_store_search_and_digest_are_volume_scoped():
    codex_memory.store_entry(
        scope="wamakologeorge-dev/amosclaude-clean",
        kind="lesson",
        title="Railway deploys read ALLOWED_HOSTS as JSON",
        content="ALLOWED_HOSTS must be a JSON list or startup fails.",
        tags=["railway", "config"],
        importance=0.9,
    )
    codex_memory.store_entry(
        scope="other/repo",
        kind="fact",
        title="Other repo fact",
        content="Unrelated knowledge that must not leak across volumes.",
    )
    hits = codex_memory.search("ALLOWED_HOSTS JSON", scope="wamakologeorge-dev/amosclaude-clean")
    assert hits and hits[0]["title"].startswith("Railway deploys")

    digest = codex_memory.digest("wamakologeorge-dev/amosclaude-clean")
    assert digest["volume"] == "wamakologeorge-dev/amosclaude-clean"
    assert digest["entry_count"] == 1
    assert "Lessons" in digest["markdown"]
    assert "Other repo fact" not in digest["markdown"]

    volumes = {volume["volume"] for volume in codex_memory.volumes()}
    assert {"wamakologeorge-dev/amosclaude-clean", "other/repo"} <= volumes


def test_invalid_kind_is_rejected():
    with pytest.raises(codex_memory.CodexMemoryError):
        codex_memory.store_entry(scope=None, kind="vibe", title="x", content="y")


def test_memory_api_requires_authentication():
    assert request("GET", "/api/v1/autonomous-codex/memory").status_code == 401
    assert request("POST", "/api/v1/autonomous-codex/memory", json={}).status_code == 401


def test_memory_api_round_trip(monkeypatch):
    monkeypatch.setattr(
        autonomous_codex, "_authenticated_user", lambda _request: {"id": 1, "name": "Owner"}
    )
    stored = request(
        "POST",
        "/api/v1/autonomous-codex/memory",
        json={
            "scope": "wamakologeorge-dev/amosclaude-clean",
            "kind": "decision",
            "title": "Deploy only through Railway",
            "content": "Production deploys target Railway project 50c395f0 only.",
            "tags": ["deployment"],
            "importance": 0.8,
        },
    )
    assert stored.status_code == 200
    assert stored.json()["stored"] is True

    listed = request(
        "GET",
        "/api/v1/autonomous-codex/memory",
        params={"query": "Railway deploy", "scope": "wamakologeorge-dev/amosclaude-clean"},
    )
    assert listed.status_code == 200
    assert listed.json()["count"] >= 1

    digest = request(
        "GET",
        "/api/v1/autonomous-codex/memory/digest",
        params={"scope": "wamakologeorge-dev/amosclaude-clean"},
    )
    assert digest.status_code == 200
    assert "Decisions" in digest.json()["markdown"]

    stats = request("GET", "/api/v1/autonomous-codex/memory/stats")
    assert stats.status_code == 200
    body = stats.json()
    assert body["memories"] >= 1
    assert "root" not in body

    bad = request(
        "POST",
        "/api/v1/autonomous-codex/memory",
        json={"kind": "nonsense", "title": "x", "content": "y"},
    )
    assert bad.status_code == 422

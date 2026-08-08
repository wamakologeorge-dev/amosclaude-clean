"""Production acceptance contract for Amosclaud API keys and connected tools."""

from __future__ import annotations

from pathlib import Path

from fastapi.routing import APIRoute
from starlette.routing import Mount

from amoscloud_ai.production_app import app


ROOT = Path(__file__).resolve().parents[1]


def _api_paths() -> set[str]:
    return {
        route.path
        for route in app.routes
        if isinstance(route, APIRoute)
    }


def test_railway_starts_the_canonical_production_app() -> None:
    railway = (ROOT / "railway.toml").read_text(encoding="utf-8")
    assert "uvicorn amoscloud_ai.production_app:app" in railway
    assert "uvicorn amoscloud_ai.owner_app:app" not in railway


def test_current_and_compatibility_key_routes_are_registered() -> None:
    paths = _api_paths()
    assert "/api/v1/agent/keys" in paths
    assert "/api/v1/agent/keys/{key_id}/rotate" in paths
    assert "/api/v1/agent/keys/{key_id}" in paths
    assert "/api/v1/autonomous/keys" in paths
    assert "/api/v1/autonomous/keys/{key_id}/rotate" in paths
    assert "/api/v1/autonomous/keys/{key_id}" in paths


def test_complete_connected_platform_is_mounted_after_key_routes() -> None:
    mounts = [route for route in app.routes if isinstance(route, Mount)]
    assert any(route.path == "" or route.path == "/" for route in mounts)

    key_route_indexes = [
        index
        for index, route in enumerate(app.routes)
        if getattr(route, "path", "") in {
            "/api/v1/agent/keys",
            "/api/v1/autonomous/keys",
        }
    ]
    platform_mount_index = next(
        index
        for index, route in enumerate(app.routes)
        if isinstance(route, Mount) and (route.path == "" or route.path == "/")
    )
    assert key_route_indexes
    assert max(key_route_indexes) < platform_mount_index

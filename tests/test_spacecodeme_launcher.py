"""Regression coverage for the authenticated SpaceCodeMe launcher."""

import asyncio
from pathlib import Path

import httpx

from amoscloud_ai.main import create_app


def test_spacecodeme_is_a_registered_authenticated_platform_route():
    paths = {str(getattr(route, "path", "")) for route in create_app().routes}
    source = Path("amoscloud_ai/main.py").read_text(encoding="utf-8")

    assert "/spacecodeme" in paths
    route = source.split('@app.get("/spacecodeme"', 1)[1].split(
        '@app.get("/workspace/{repository_id}"', 1
    )[0]
    assert "get_user_from_session" in route
    assert 'RedirectResponse("/login", status_code=302)' in route
    assert 'FileResponse(web_dir / "spacecodeme.html")' in route


def test_spacecodeme_redirects_anonymous_visitors_to_login():
    async def request():
        transport = httpx.ASGITransport(app=create_app())
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test", follow_redirects=False
        ) as client:
            return await client.get("/spacecodeme")

    response = asyncio.run(request())
    assert response.status_code == 302
    assert response.headers["location"] == "/login"


def test_spacecodeme_launcher_has_safe_loading_and_legacy_url_handling():
    page = Path("web/spacecodeme.html").read_text(encoding="utf-8")

    assert "location.replace('/spacecodeme')" in page
    assert "if (!response.ok)" in page
    assert "button:disabled" in page
    assert "node.textContent = label" in page
    assert "location.assign(`/workspace/${encodeURIComponent(repo.value)}`)" in page

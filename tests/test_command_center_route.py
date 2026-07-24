from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_command_center_is_an_authenticated_page():
    source = (ROOT / "amoscloud_ai/main.py").read_text(encoding="utf-8")
    route = source.split('@app.get("/command-center"', 1)[1].split('@app.get("/admin"', 1)[0]
    assert "get_user_from_session" in route
    assert 'RedirectResponse("/login", status_code=302)' in route
    assert 'FileResponse(web_dir / "command-center.html")' in route


def test_command_center_uses_session_authenticated_native_apis():
    html = (ROOT / "web/command-center.html").read_text(encoding="utf-8")
    script = (ROOT / "web/command-center.js").read_text(encoding="utf-8")
    assert '/static/command-center.css' in html
    assert '/static/command-center.js' in html
    for endpoint in ('/api/v1/repositories', '/issues', '/api/v1/agent/run'):
        assert endpoint in script
    assert "credentials: 'same-origin'" in script
    assert "repository_id: repository.id" in script
    assert "repository_name: repository.name" in script
    assert "X-Amosclaud-Owner-Key" not in script
    assert "does not promise file changes, commits, or pull requests" in html.lower()


def test_command_center_redirects_anonymous_users_and_serves_its_assets():
    import asyncio

    import httpx

    from amoscloud_ai.main import create_app

    async def check_routes():
        transport = httpx.ASGITransport(app=create_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            page = await client.get("/command-center", follow_redirects=False)
            script = await client.get("/static/command-center.js")
            return page, script

    page, script = asyncio.run(check_routes())
    assert page.status_code == 302
    assert page.headers["location"] == "/login"
    assert script.status_code == 200
    assert "repository_id" in script.text

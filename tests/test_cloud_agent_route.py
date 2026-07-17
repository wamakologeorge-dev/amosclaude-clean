from pathlib import Path


def test_cloud_agent_is_canonical_authenticated_workspace():
    source = Path("amoscloud_ai/main.py").read_text(encoding="utf-8")

    assert '@app.get("/cloud/agent"' in source
    assert 'return FileResponse(web_dir / "index.html")' in source
    assert 'RedirectResponse("/cloud/agent", status_code=308)' in source
    assert 'RedirectResponse("/cloud/agent", status_code=302)' in source


def test_cloud_agent_route_still_requires_login():
    source = Path("amoscloud_ai/main.py").read_text(encoding="utf-8")
    route = source.split('@app.get("/cloud/agent"', 1)[1].split('@app.get("/autonomous"', 1)[0]

    assert 'get_user_from_session' in route
    assert 'RedirectResponse("/login", status_code=302)' in route

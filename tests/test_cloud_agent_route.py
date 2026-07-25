from pathlib import Path

from amoscloud_ai.main import create_app


def test_cloud_agent_is_the_only_public_agent_workspace_route():
    source = Path("amoscloud_ai/main.py").read_text(encoding="utf-8")
    paths = {str(getattr(route, "path", "")) for route in create_app().routes}

    assert "/cloud/agent" in paths
    # The legacy AmoModel settings hub was moved, not deleted.
    assert "/cloud/agent/legacy" in paths
    assert "/autonomous" not in paths
    assert 'return FileResponse(web_dir / "command-center.html")' in source
    assert 'return FileResponse(web_dir / "index.html")' in source
    assert '@app.get("/autonomous"' not in source
    assert 'RedirectResponse("/cloud/agent", status_code=308)' not in source


def test_cloud_agent_route_still_requires_login():
    source = Path("amoscloud_ai/main.py").read_text(encoding="utf-8")
    route = source.split('@app.get("/cloud/agent"', 1)[1].split('@app.get("/"', 1)[0]

    assert "get_user_from_session" in route
    assert 'RedirectResponse("/login", status_code=302)' in route


def test_legacy_agent_route_is_gated_exactly_like_the_primary_route():
    source = Path("amoscloud_ai/main.py").read_text(encoding="utf-8")
    legacy = source.split('@app.get("/cloud/agent/legacy"', 1)[1]
    legacy = legacy.split('@app.get("/"', 1)[0]

    assert "get_user_from_session" in legacy
    assert 'RedirectResponse("/login", status_code=302)' in legacy
    assert 'return FileResponse(web_dir / "index.html")' in legacy

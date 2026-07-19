from pathlib import Path


def test_bundles_dashboard_is_visible_and_connected():
    root = Path(__file__).resolve().parents[1]
    page = (root / "web" / "bundles.html").read_text(encoding="utf-8")
    script = (root / "web" / "bundles.js").read_text(encoding="utf-8")
    index = (root / "web" / "index.html").read_text(encoding="utf-8")

    assert "Amosclaud Bundles" in page
    assert 'id="bundle-form"' in page
    assert 'id="bundle-list"' in page
    assert "/api/v1/bundles" in script
    assert "Download .amosbundle" in script
    assert 'href="/bundles"' in index


def test_bundles_page_route_is_registered():
    root = Path(__file__).resolve().parents[1]
    route = (root / "amoscloud_ai" / "api" / "routes" / "bundle_pages.py").read_text(encoding="utf-8")
    health = (root / "amoscloud_ai" / "api" / "routes" / "health.py").read_text(encoding="utf-8")

    assert '@router.get("/bundles"' in route
    assert 'FileResponse(WEB_ROOT / "bundles.html")' in route
    assert "router.include_router(bundle_pages.router)" in health

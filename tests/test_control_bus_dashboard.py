from pathlib import Path

from amoscloud_ai.main import create_app


def test_control_bus_dashboard_route_is_registered():
    app = create_app()
    paths = {route.path for route in app.routes}
    assert "/control-bus" in paths


def test_control_bus_dashboard_assets_exist_and_use_live_data_only():
    root = Path(__file__).resolve().parents[1] / "web"
    html = (root / "amosclaud-control-bus.html").read_text(encoding="utf-8")
    js = (root / "amosclaud-control-bus.js").read_text(encoding="utf-8")
    css = (root / "amosclaud-control-bus.css").read_text(encoding="utf-8")

    assert "/api/v1/server/cb/amosclaud" in js
    assert "command-output" in html
    assert "provider-grid" in html
    assert ".metrics" in css
    assert "bundle-name.Amosclaud.bytes" not in html
    assert ">0</strong>" not in html
    assert "Loading…" not in html
    assert "No bundles were returned by the Amosclaud API." in js

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "web" / "big-ci.html"
JS = ROOT / "web" / "big-ci.js"
PRODUCTS = ROOT / "web" / "operator-products.html"


def test_big_ci_dashboard_is_deployed() -> None:
    html = HTML.read_text(encoding="utf-8")
    source = JS.read_text(encoding="utf-8")
    assert "Amosclaud BIG CI" in html or ">BIG CI<" in html
    assert 'id="ci-form"' in html
    assert 'src="/static/big-ci.js"' in html
    assert "/api/v1/repositories" in source
    assert "/api/v1/tasks" in source
    assert "/logs`" in source


def test_big_ci_uses_shared_task_router_and_fixer_handoff() -> None:
    source = JS.read_text(encoding="utf-8")
    assert "mode: 'test'" in source
    assert "product: 'big-ci'" in source
    assert "requested_from: 'amosclaud-platform'" in source
    assert "mode: 'fix'" in source
    assert "source_ci_task_id" in source
    assert "require_approval: true" in source


def test_big_ci_is_discoverable_as_a_platform_product() -> None:
    products = PRODUCTS.read_text(encoding="utf-8")
    assert "Amosclaud BIG CI" in products
    assert 'href="/static/big-ci.html"' in products
    assert "Send failed runs directly to Amosclaud Fixer" in products

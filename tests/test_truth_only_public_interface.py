from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_public_page_has_no_static_success_or_online_claims():
    html = _read("web/index.html").lower()

    for forbidden in (
        "autonomous online",
        "badge badge-success\">ready",
        "creates, fixes, tests, deploys",
        "all five real bundle types",
    ):
        assert forbidden not in html


def test_public_page_explains_unverified_state():
    html = _read("web/index.html")

    assert "Status not checked" in html
    assert "Not verified" in html
    assert "must not replace them with a success message" in html
    assert "until the running backend returns evidence" in html


def test_public_navigation_is_limited_to_repository_backed_surfaces():
    html = _read("web/index.html")

    assert '>Chat<' in html
    assert '>Repository<' in html
    assert '>Check server<' in html
    assert 'href="/bundles">Results<' not in html


def test_truth_inventory_distinguishes_source_presence_from_operation():
    inventory = _read("docs/TRUTH_ONLY_SERVICE_INVENTORY.md")

    assert "does not prove that a production deployment is configured or healthy" in inventory
    assert "Static labels such as online, ready, healthy, or running are not evidence" in inventory
    assert "configuration-required" in inventory
    assert "planned, queued, or accepted operation as completed" in inventory

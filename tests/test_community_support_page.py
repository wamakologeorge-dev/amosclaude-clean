from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_public_support_route_and_official_payment_links() -> None:
    health = _read("amoscloud_ai/api/routes/health.py")
    page = _read("web/support.html")

    assert '@router.get("/support", include_in_schema=False)' in health
    assert 'FileResponse(WEB_DIR / "support.html")' in health
    assert "https://cash.app/$kenjamakulu" in page
    assert "https://cash.app/launch/bitcoin/$kenjamakulu/pPi5bQWHLA" in page
    assert "Contribute with Cash App" in page
    assert "Contribute with Bitcoin" in page
    assert 'target="_blank"' in page
    assert 'rel="noopener noreferrer"' in page


def test_support_page_is_transparent_about_verification_and_service_limits() -> None:
    page = _read("web/support.html")
    policy = _read("docs/community-support-policy.md")

    assert "Neither payment link automatically activates Amosclaud" in page
    assert "must be verified before service capacity is assigned" in page
    assert "Service pauses when the verified allocation is exhausted" in page
    assert (
        "A screenshot, transaction reference, or payment-link visit does not "
        "independently activate service"
    ) in policy


def test_support_page_contains_non_refundable_and_tax_status_disclosures() -> None:
    page = _read("web/support.html")
    policy = _read("docs/community-support-policy.md")

    assert "Non-refundable policy" in page
    assert "non-refundable after they are sent" in page
    assert "except where a refund is required by applicable law" in page
    assert "does not claim that Amosclaud is a tax-exempt charity" in page
    assert "not represented as tax-deductible" in page
    assert (
        "does not claim that Amosclaud is a legally registered tax-exempt charity"
    ) in policy


def test_public_pages_make_support_discoverable() -> None:
    status = _read("web/status.html")
    login = _read("web/login.html")

    assert 'href="/support">Support development</a>' in status
    assert 'href="/support">Support open-source development</a>' in login

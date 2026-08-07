from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_runtime_mounts_verified_instant_payment_router() -> None:
    main = read("amoscloud_ai/main.py")
    assert "instant_payments," in main
    assert 'app.include_router(instant_payments.router, prefix="/api/v1")' in main


def test_plan_page_offers_provider_verified_cash_app_and_bitcoin() -> None:
    page = read("web/plans.html")
    script = read("web/plans.js")
    assert "Cash App Pay" in page
    assert "Bitcoin" in page
    assert "/static/plans.js" in page
    assert "/api/v1/billing/instant/cash-app/complete" in script
    assert "/api/v1/billing/instant/bitcoin/start" in script
    assert "/api/v1/billing/instant/orders/" in script
    assert "$cashtag" not in page.lower()


def test_square_csp_and_production_configuration_are_documented() -> None:
    security = read("amoscloud_ai/security.py")
    example = read(".env.production.example")
    assert "https://web.squarecdn.com" in security
    assert "https://sandbox.web.squarecdn.com" in security
    https_urls = [
        token.strip('\'",()[]{}')
        for token in security.split()
        if token.startswith("https://")
    ]
    assert any(
        (urlparse(url).hostname or "") == "pci-connect.squareup.com"
        for url in https_urls
    )
    for variable in (
        "AMOSCLAUD_INSTANT_PRICE_CENTS=1500",
        "AMOSCLAUD_INSTANT_ACCESS_DAYS=30",
        "SQUARE_APPLICATION_ID=",
        "SQUARE_WEBHOOK_NOTIFICATION_URL=",
        "BTCPAY_SERVER_URL=",
        "BTCPAY_STORE_ID=",
    ):
        assert variable in example

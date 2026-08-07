from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _https_hostnames(source: str) -> set[str]:
    hostnames: set[str] = set()
    for token in source.split():
        candidate = token.strip("'\",()[]{}")
        if not candidate.startswith("https://"):
            continue
        hostname = (urlparse(candidate).hostname or "").lower()
        if hostname:
            hostnames.add(hostname)
    return hostnames


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
    square_hosts = _https_hostnames(security)
    assert {
        "web.squarecdn.com",
        "sandbox.web.squarecdn.com",
        "pci-connect.squareup.com",
    } <= square_hosts
    for variable in (
        "AMOSCLAUD_INSTANT_PRICE_CENTS=1500",
        "AMOSCLAUD_INSTANT_ACCESS_DAYS=30",
        "SQUARE_APPLICATION_ID=",
        "SQUARE_WEBHOOK_NOTIFICATION_URL=",
        "BTCPAY_SERVER_URL=",
        "BTCPAY_STORE_ID=",
    ):
        assert variable in example

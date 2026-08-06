from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from amoscloud_ai import agent_credit_billing
from amoscloud_ai.api.routes import provider_api

ROOT = Path(__file__).resolve().parents[1]


def _database() -> sqlite3.Connection:
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("""CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            email TEXT NOT NULL,
            name TEXT
        )""")
    db.execute("INSERT INTO users(id,email,name) VALUES (1,'owner@example.com','Owner')")
    db.commit()
    return db


def _clear_stripe_environment(monkeypatch) -> None:
    for name in (
        "STRIPE_SECRET_KEY",
        "STRIPE_WEBHOOK_SECRET",
        "STRIPE_AGENT_CURRENCY",
        "STRIPE_AGENT_STARTER_PRICE_ID",
        "STRIPE_AGENT_STARTER_AMOUNT_CENTS",
        "STRIPE_AGENT_BUILDER_PRICE_ID",
        "STRIPE_AGENT_BUILDER_AMOUNT_CENTS",
        "STRIPE_AGENT_STUDIO_PRICE_ID",
        "STRIPE_AGENT_STUDIO_AMOUNT_CENTS",
    ):
        monkeypatch.delenv(name, raising=False)


def test_pack_reports_every_missing_checkout_requirement(monkeypatch):
    _clear_stripe_environment(monkeypatch)

    pack = agent_credit_billing.public_pack(agent_credit_billing.get_pack("starter"))

    assert pack["available"] is False
    assert "STRIPE_SECRET_KEY" in pack["configuration_message"]
    assert "STRIPE_WEBHOOK_SECRET" in pack["configuration_message"]
    assert "STRIPE_AGENT_STARTER_PRICE_ID" in pack["configuration_message"]


def test_inline_amount_creates_a_stripe_checkout_line_item(monkeypatch):
    _clear_stripe_environment(monkeypatch)
    monkeypatch.setenv("STRIPE_AGENT_CURRENCY", "usd")
    monkeypatch.setenv("STRIPE_AGENT_STARTER_AMOUNT_CENTS", "1250")

    item = agent_credit_billing.checkout_line_item(agent_credit_billing.get_pack("starter"))

    assert item == {
        "price_data": {
            "currency": "usd",
            "unit_amount": 1250,
            "product_data": {
                "name": "Amosclaud Agent Credits — Starter",
                "description": "1,000 prepaid Amosclaud agent credits",
                "metadata": {"pack": "starter", "credits": "1000"},
            },
        },
        "quantity": 1,
    }


def test_paid_checkout_credits_fixed_pack_once(monkeypatch):
    _clear_stripe_environment(monkeypatch)
    monkeypatch.setenv("STRIPE_AGENT_CURRENCY", "usd")
    monkeypatch.setenv("STRIPE_AGENT_STARTER_AMOUNT_CENTS", "1000")
    db = _database()
    session = {
        "id": "cs_test_paid_once",
        "payment_status": "paid",
        "client_reference_id": "1",
        "amount_total": 1000,
        "currency": "usd",
        "metadata": {
            "kind": "agent_tokens",
            "amosclaud_user_id": "1",
            "pack": "starter",
            "credits": "999999999",
        },
    }

    first = agent_credit_billing.settle_paid_checkout(
        db,
        session,
        expected_user_id=1,
    )
    second = agent_credit_billing.settle_paid_checkout(
        db,
        session,
        expected_user_id=1,
    )

    assert first == (True, 1000)
    assert second == (False, 1000)
    ledger = db.execute("SELECT delta,reference FROM agent_token_ledger").fetchall()
    assert [tuple(row) for row in ledger] == [(1000, "stripe_checkout:cs_test_paid_once")]


def test_checkout_rejects_an_amount_that_does_not_match_pack(monkeypatch):
    _clear_stripe_environment(monkeypatch)
    monkeypatch.setenv("STRIPE_AGENT_STARTER_AMOUNT_CENTS", "1000")
    db = _database()

    with pytest.raises(ValueError, match="amount does not match"):
        agent_credit_billing.settle_paid_checkout(
            db,
            {
                "id": "cs_test_wrong_amount",
                "payment_status": "paid",
                "client_reference_id": "1",
                "amount_total": 1,
                "currency": "usd",
                "metadata": {
                    "kind": "agent_tokens",
                    "amosclaud_user_id": "1",
                    "pack": "starter",
                },
            },
            expected_user_id=1,
        )


def test_checkout_requires_webhook_before_opening_stripe(monkeypatch):
    _clear_stripe_environment(monkeypatch)
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_safe")
    monkeypatch.setenv("STRIPE_AGENT_STARTER_PRICE_ID", "price_starter")
    monkeypatch.setattr(
        provider_api,
        "_user",
        lambda _token: {"id": 1, "email": "owner@example.com"},
    )

    with pytest.raises(HTTPException) as caught:
        provider_api.token_checkout(
            provider_api.TokenCheckout(pack="starter"),
            amos_session="session",
        )

    assert caught.value.status_code == 503
    assert "STRIPE_WEBHOOK_SECRET" in str(caught.value.detail)


def test_checkout_redirects_to_hosted_stripe_and_returns_to_api_access(monkeypatch):
    _clear_stripe_environment(monkeypatch)
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_safe")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_safe")
    monkeypatch.setenv("STRIPE_AGENT_STARTER_PRICE_ID", "price_starter")
    monkeypatch.setenv("AMOSCLAUD_PUBLIC_URL", "https://www.amosclaud.com")
    monkeypatch.setattr(
        provider_api,
        "_user",
        lambda _token: {"id": 1, "email": "owner@example.com"},
    )
    monkeypatch.setattr(
        provider_api,
        "_stripe_customer_id",
        lambda _user: "cus_amosclaud",
    )
    captured: dict[str, object] = {}

    def create_session(**parameters):
        captured.update(parameters)
        return SimpleNamespace(
            id="cs_test_checkout",
            url="https://checkout.stripe.com/c/pay/cs_test_checkout",
        )

    monkeypatch.setattr(
        provider_api.stripe.checkout.Session,
        "create",
        create_session,
    )

    result = provider_api.token_checkout(
        provider_api.TokenCheckout(pack="starter"),
        amos_session="session",
    )

    assert result["url"].startswith("https://checkout.stripe.com/")
    assert captured["customer"] == "cus_amosclaud"
    assert captured["line_items"] == [{"price": "price_starter", "quantity": 1}]
    assert captured["success_url"] == (
        "https://www.amosclaud.com/api-access?checkout=success" "&session_id={CHECKOUT_SESSION_ID}"
    )
    assert captured["cancel_url"] == ("https://www.amosclaud.com/api-access?checkout=cancelled")
    assert "payment_method_types" not in captured


def test_mobile_page_uses_cash_app_and_bitcoin_for_agent_credit_payments():
    page = (ROOT / "web" / "api-access.html").read_text(encoding="utf-8")

    assert "https://cash.app/$kenjamakulu" in page
    assert "https://cash.app/launch/bitcoin/$kenjamakulu/pPi5bQWHLA" in page
    assert "Cash App and Cash App Bitcoin are the only payment options currently enabled" in page
    assert "Credits are added only after Amosclaud verifies the payment" in page
    assert "Never include passwords, API keys, recovery codes, or private keys" in page
    assert "Pay with Cash App" in page
    assert "Pay with Bitcoin" in page
    assert "Stripe" not in page
    assert "/api/v1/provider/tokens/checkout" not in page


def test_billing_webhook_handles_delayed_bank_payment_success():
    billing = (ROOT / "amoscloud_ai" / "api" / "routes" / "billing.py").read_text(encoding="utf-8")

    assert "checkout.session.async_payment_succeeded" in billing
    assert "settle_paid_checkout(db, obj)" in billing
    assert "reference=event_id" not in billing

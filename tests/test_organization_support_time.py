from __future__ import annotations

import sqlite3

from amoscloud_ai import agent_tokens, organization_support


def _database() -> sqlite3.Connection:
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute(
        """CREATE TABLE users (
               id INTEGER PRIMARY KEY,
               email TEXT NOT NULL,
               is_admin INTEGER NOT NULL DEFAULT 0
           )"""
    )
    db.execute("INSERT INTO users(id,email,is_admin) VALUES (1,'builder@example.com',0)")
    db.commit()
    return db


def test_higher_support_tiers_provide_more_hosted_working_time(monkeypatch) -> None:
    for name in (
        "AMOSCLAUD_SUPPORT_STARTER_SECONDS",
        "AMOSCLAUD_SUPPORT_BUILDER_SECONDS",
        "AMOSCLAUD_SUPPORT_STUDIO_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)

    tiers = {tier["id"]: tier for tier in organization_support.support_tiers()}

    assert tiers["starter"]["working_hours"] == 10
    assert tiers["builder"]["working_hours"] == 60
    assert tiers["studio"]["working_hours"] == 240
    assert tiers["starter"]["working_seconds"] < tiers["builder"]["working_seconds"]
    assert tiers["builder"]["working_seconds"] < tiers["studio"]["working_seconds"]


def test_verified_cash_app_payment_adds_credits_and_working_time_once() -> None:
    db = _database()

    assert agent_tokens.credit_tokens(
        db,
        1,
        1_000,
        reason="cash_app_payment",
        reference="cash-receipt-1001",
    )
    assert organization_support.support_wallet(db, 1) == {
        "remaining_seconds": 36_000,
        "lifetime_seconds": 36_000,
    }
    assert agent_tokens.api_access_is_activated(db, 1)

    assert not agent_tokens.credit_tokens(
        db,
        1,
        1_000,
        reason="bitcoin_payment",
        reference="cash-receipt-1001",
    )
    assert organization_support.support_wallet(db, 1)["remaining_seconds"] == 36_000


def test_hosted_tool_time_expires_and_disables_customer_api_access(monkeypatch) -> None:
    monkeypatch.setenv("AMOSCLAUD_SUPPORT_STARTER_SECONDS", "60")
    db = _database()
    assert agent_tokens.credit_tokens(
        db,
        1,
        1_000,
        reason="bitcoin_payment",
        reference="bitcoin-tx-2002",
    )

    charged, remaining = organization_support.debit_support_time(
        db,
        1,
        60,
        reference="tool-time:operation-1",
    )

    assert charged is True
    assert remaining == 0
    assert not agent_tokens.api_access_is_activated(db, 1)
    charged_again, remaining_again = organization_support.debit_support_time(
        db,
        1,
        60,
        reference="tool-time:operation-2",
    )
    assert charged_again is False
    assert remaining_again == 0


def test_administrator_keeps_internal_maintenance_access() -> None:
    db = _database()

    assert agent_tokens.api_access_is_activated(db, 1, is_admin=True)


def test_support_page_embeds_official_payment_methods_and_disclosure() -> None:
    page = organization_support.organization_support_page().body.decode("utf-8")

    assert "https://cash.app/$kenjamakulu" in page
    assert "https://cash.app/launch/bitcoin/$kenjamakulu/pPi5bQWHLA" in page
    assert "Unlock hosted working time" in page
    assert "10 hosted hours" in page
    assert "60 hosted hours" in page
    assert "240 hosted hours" in page
    assert "not a tax-deductible charitable donation" in page


def test_production_gateway_wraps_platform_and_mcp_with_support_gate() -> None:
    source = open("amoscloud_ai/combined_app.py", encoding="utf-8").read()

    assert "class HostedToolSupportASGI" in source
    assert 'app.mount("/mcp", BearerProtectedASGI' in source
    assert 'app.mount("/", HostedToolSupportASGI(platform_app)' in source
    assert "organization_support_time_required" not in source

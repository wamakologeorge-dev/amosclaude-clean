from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from amoscloud_ai.agent_tokens import issue_api_key
from amoscloud_ai.api.routes import auth, openai_compat, provider_api


def _insert_user(*, name: str, email: str, is_admin: bool) -> int:
    with auth._connect() as db:
        cursor = db.execute(
            """INSERT INTO users(
                   name,email,password_hash,provider,is_admin,created_at
               ) VALUES (?,?,NULL,'password',?,?)""",
            (
                name,
                email,
                int(is_admin),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        db.commit()
        return int(cursor.lastrowid)


def test_cash_app_or_bitcoin_payment_is_required_before_api_key_activation(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(auth, "DB_PATH", tmp_path / "paid-api.db")
    customer_id = _insert_user(
        name="Customer",
        email="customer@example.com",
        is_admin=False,
    )
    admin_id = _insert_user(
        name="Owner",
        email="owner@example.com",
        is_admin=True,
    )
    actors = {
        "customer": {
            "id": customer_id,
            "email": "customer@example.com",
            "name": "Customer",
            "is_admin": 0,
        },
        "admin": {
            "id": admin_id,
            "email": "owner@example.com",
            "name": "Owner",
            "is_admin": 1,
        },
    }
    monkeypatch.setattr(provider_api, "_user", lambda token: actors[str(token)])

    with pytest.raises(HTTPException) as unpaid:
        provider_api.create_key(
            provider_api.KeyCreate(label="Unpaid installation"),
            amos_session="customer",
        )
    assert unpaid.value.status_code == 402
    assert "Cash App or Bitcoin" in str(unpaid.value.detail)

    activation = provider_api.activate_paid_api_access(
        provider_api.PaymentActivation(
            user_email="customer@example.com",
            pack="starter",
            method="cash_app",
            payment_reference="cash-receipt-1001",
        ),
        amos_session="admin",
    )
    assert activation["activated"] is True
    assert activation["credits_added"] == 1_000
    assert activation["verified_by"] == admin_id

    key = provider_api.create_key(
        provider_api.KeyCreate(label="Paid installation"),
        amos_session="customer",
    )
    assert key["activated"] is True
    assert key["api_key"].startswith("amos_live_")

    status = provider_api.token_status(amos_session="customer")
    assert status["api_activated"] is True
    assert status["checkout_provider"] == "cash_app_or_bitcoin_manual_verification"
    assert {method["id"] for method in status["payment_methods"]} == {
        "cash_app",
        "bitcoin",
    }


def test_duplicate_payment_reference_cannot_credit_an_account_twice(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(auth, "DB_PATH", tmp_path / "duplicate-payment.db")
    customer_id = _insert_user(
        name="Customer",
        email="customer@example.com",
        is_admin=False,
    )
    admin_id = _insert_user(
        name="Owner",
        email="owner@example.com",
        is_admin=True,
    )
    actors = {
        "admin": {
            "id": admin_id,
            "email": "owner@example.com",
            "name": "Owner",
            "is_admin": 1,
        }
    }
    monkeypatch.setattr(provider_api, "_user", lambda token: actors[str(token)])
    body = provider_api.PaymentActivation(
        user_email="customer@example.com",
        pack="builder",
        method="bitcoin",
        payment_reference="bitcoin-tx-abc123",
    )

    first = provider_api.activate_paid_api_access(body, amos_session="admin")
    assert first["user_id"] == customer_id
    assert first["credits_added"] == 5_000

    with pytest.raises(HTTPException) as duplicate:
        provider_api.activate_paid_api_access(body, amos_session="admin")
    assert duplicate.value.status_code == 409


def test_existing_unpaid_keys_are_blocked_in_both_api_surfaces(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(auth, "DB_PATH", tmp_path / "legacy-key.db")
    customer_id = _insert_user(
        name="Customer",
        email="customer@example.com",
        is_admin=False,
    )
    with auth._connect() as db:
        _, raw_key, _ = issue_api_key(db, customer_id, "Legacy unpaid key")

    for authenticate in (provider_api._authenticate, openai_compat._authenticate):
        with pytest.raises(HTTPException) as unpaid:
            authenticate(f"Bearer {raw_key}")
        assert unpaid.value.status_code == 402
        assert "Cash App or Bitcoin" in str(unpaid.value.detail)


def test_platform_admin_can_create_an_internal_key_without_customer_payment(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(auth, "DB_PATH", tmp_path / "admin-key.db")
    admin_id = _insert_user(
        name="Owner",
        email="owner@example.com",
        is_admin=True,
    )
    monkeypatch.setattr(
        provider_api,
        "_user",
        lambda _token: {
            "id": admin_id,
            "email": "owner@example.com",
            "name": "Owner",
            "is_admin": 1,
        },
    )

    key = provider_api.create_key(
        provider_api.KeyCreate(label="Owner internal installation"),
        amos_session="admin",
    )
    assert key["activated"] is True

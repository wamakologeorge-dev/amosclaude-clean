"""Tests for lightweight account management endpoints."""

import importlib
import sys
import types
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient


def _make_anthropic_stub():
    module = types.ModuleType("anthropic")

    class _Message:
        def __init__(self, text):
            self.content = [MagicMock(text=text)]

    class _Messages:
        def create(self, **kwargs):
            return _Message("mock build plan")

    class Anthropic:
        def __init__(self, **kwargs):
            self.messages = _Messages()

    module.Anthropic = Anthropic
    return module


@pytest.fixture()
def app_module(monkeypatch):
    monkeypatch.setitem(sys.modules, "anthropic", _make_anthropic_stub())
    module = importlib.import_module("src.amoscloud_ai.main")
    importlib.reload(module)
    return module


@pytest.fixture()
def client(app_module):
    with TestClient(app_module.app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def clear_accounts(app_module):
    with app_module.accounts_lock:
        app_module.accounts.clear()
    yield
    with app_module.accounts_lock:
        app_module.accounts.clear()


def test_delete_account_returns_confirmation(client, app_module):
    create_resp = client.post(
        "/accounts",
        json={"username": "alice", "email": "alice@example.com"},
    )
    assert create_resp.status_code == 201

    account_id = create_resp.json()["account"]["id"]
    delete_resp = client.delete(f"/accounts/{account_id}")

    assert delete_resp.status_code == 200
    assert delete_resp.json() == {"deleted": True, "account_id": account_id}
    assert app_module.accounts == {}


def test_delete_missing_account_returns_404(client):
    resp = client.delete("/accounts/does-not-exist")

    assert resp.status_code == 404
    assert resp.json()["detail"] == "account not found"

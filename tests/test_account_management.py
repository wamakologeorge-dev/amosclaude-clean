"""Tests for lightweight account management endpoints."""

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
            return _Message("## Project Plan\n- Step 1\n## Implementation Outline\n- file.py")

    class Anthropic:
        def __init__(self, **kwargs):
            self.messages = _Messages()

    module.Anthropic = Anthropic
    return module


sys.modules.setdefault("anthropic", _make_anthropic_stub())

from src.amoscloud_ai.main import app, _accounts  # noqa: E402


@pytest.fixture(autouse=True)
def clear_accounts():
    _accounts.clear()
    yield
    _accounts.clear()


client = TestClient(app)


def test_delete_account_returns_confirmation():
    create_resp = client.post(
        "/accounts",
        json={"username": "alice", "email": "alice@example.com"},
    )
    assert create_resp.status_code == 201

    account_id = create_resp.json()["account"]["id"]
    delete_resp = client.delete(f"/accounts/{account_id}")

    assert delete_resp.status_code == 200
    assert delete_resp.json() == {"deleted": True, "account_id": account_id}
    assert _accounts == {}


def test_delete_missing_account_returns_404():
    resp = client.delete("/accounts/does-not-exist")

    assert resp.status_code == 404
    assert resp.json()["detail"] == "account not found"

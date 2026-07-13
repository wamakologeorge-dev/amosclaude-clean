from pathlib import Path

import pytest

from amoscloud_ai.core.access import AccessMode, AccessPolicy
from amoscloud_ai.core.registry import ServiceRegistry
from amoscloud_ai.core.vault import AmosclaudVault, VaultError


def test_vault_encrypts_and_masks_values(tmp_path: Path):
    db_path = tmp_path / "core.db"
    vault = AmosclaudVault(db_path=db_path, master_key="owner-secret")
    vault.set("github_token", "token-value", actor_id=7)

    assert vault.get("GITHUB_TOKEN") == "token-value"
    listed = vault.list_masked()
    assert listed[0]["name"] == "GITHUB_TOKEN"
    assert listed[0]["value"] == "••••••••"
    assert listed[0]["updated_by"] == 7

    raw = db_path.read_bytes()
    assert b"token-value" not in raw


def test_vault_rejects_wrong_master_key(tmp_path: Path):
    db_path = tmp_path / "core.db"
    AmosclaudVault(db_path=db_path, master_key="correct").set("VALUE", "protected")

    with pytest.raises(VaultError, match="cannot be decrypted"):
        AmosclaudVault(db_path=db_path, master_key="wrong").get("VALUE")


def test_vault_requires_master_key(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("AMOSCLAUD_MASTER_KEY", raising=False)
    with pytest.raises(VaultError, match="required"):
        AmosclaudVault(db_path=tmp_path / "core.db")


def test_service_registry_registers_resolves_and_removes(tmp_path: Path):
    registry = ServiceRegistry(tmp_path / "registry.db")
    registry.register("amos://model", "model", "http://model:11434")

    assert registry.resolve("amos://model") == "http://model:11434"
    services = registry.list()
    assert services[0]["name"] == "amos://model"
    assert services[0]["healthy"] is True

    assert registry.heartbeat("amos://model") is True
    assert registry.remove("amos://model") is True
    assert registry.resolve("amos://model") is None


def test_local_access_mode_rejects_non_loopback_clients():
    policy = AccessPolicy(mode=AccessMode.LOCAL, owner_email="owner@example.com")
    assert policy.allows_client("127.0.0.1") is True
    assert policy.allows_client("::1") is True
    assert policy.allows_client("192.168.1.10") is False
    assert policy.allows_client("8.8.8.8") is False


def test_lan_access_mode_allows_private_network_only():
    policy = AccessPolicy(mode=AccessMode.LAN, owner_email="owner@example.com")
    assert policy.allows_client("192.168.1.10") is True
    assert policy.allows_client("10.0.0.5") is True
    assert policy.allows_client("8.8.8.8") is False


def test_public_access_mode_and_role_mapping():
    policy = AccessPolicy(mode=AccessMode.PUBLIC, owner_email="owner@example.com")
    assert policy.allows_client("8.8.8.8") is True
    assert policy.role_for(None) == "visitor"
    assert policy.role_for({"email": "member@example.com", "is_admin": 0}) == "member"
    assert policy.role_for({"email": "admin@example.com", "is_admin": 1}) == "administrator"
    assert policy.role_for({"email": "OWNER@example.com", "is_admin": 1}) == "owner"
    assert policy.public_summary() == {
        "mode": "public",
        "public_signup": True,
        "lan_access": True,
        "public_access": True,
    }

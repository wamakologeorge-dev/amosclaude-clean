"""Focused tests for the Amosclaud Registry."""

import sqlite3
from pathlib import Path

import pytest
from pydantic import ValidationError

from amoscloud_ai import registry
from amoscloud_ai.api.routes.registry import RegistryEntryCreate, RegistryEntryUpdate


def memory_db() -> sqlite3.Connection:
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    return db


def custom_entry() -> dict:
    return {
        "id": "skill.example-review",
        "kind": "skill",
        "title": "Example review skill",
        "description": "Provides bounded example repository review metadata.",
        "version": "0.1.0",
        "status": "experimental",
        "trust": "community",
        "entrypoint": "skills/example-review/SKILL.md",
        "source_url": "https://github.com/example/example-review",
        "capabilities": ["review", "explanation"],
        "platforms": ["cli", "vscode"],
        "metadata": {"license": "example"},
    }


def test_builtin_registry_seeds_one_autonomous_identity_and_editor_clients():
    with memory_db() as db:
        entries = registry.list_entries(db)
        summary = registry.registry_summary(db)

    ids = {entry["id"] for entry in entries}
    assert summary["identity"] == {"name": "Amosclaud Autonomous", "type": "one-agent"}
    assert summary["entry_count"] == len(entries)
    assert {
        "capability.autonomous",
        "client.ide-cli",
        "client.vscode",
        "client.xcode",
        "service.copilot-api",
        "service.node-control-plane",
    }.issubset(ids)
    assert all(entry["manifest_digest"] for entry in entries)


def test_registry_filters_by_kind_capability_and_platform():
    with memory_db() as db:
        clients = registry.list_entries(db, kind="client")
        chat_clients = registry.list_entries(db, kind="client", capability="chat")
        xcode_entries = registry.list_entries(db, platform="xcode")

    assert {entry["id"] for entry in clients} == {
        "client.ide-cli",
        "client.vscode",
        "client.xcode",
    }
    assert {entry["id"] for entry in chat_clients} == {
        "client.ide-cli",
        "client.vscode",
        "client.xcode",
    }
    assert {entry["id"] for entry in xcode_entries} >= {
        "client.xcode",
        "capability.autonomous",
    }


def test_custom_entry_lifecycle_is_durable_and_disabled_entries_are_hidden():
    with memory_db() as db:
        created = registry.create_entry(db, custom_entry(), created_by=7)
        original_digest = created["manifest_digest"]
        updated = registry.update_entry(
            db,
            created["id"],
            {"status": "active", "title": "Approved example review skill"},
        )
        disabled = registry.disable_entry(db, created["id"])
        visible = registry.list_entries(db)
        all_entries = registry.list_entries(db, include_disabled=True)

    assert created["immutable"] is False
    assert updated["status"] == "active"
    assert updated["manifest_digest"] != original_digest
    assert disabled["status"] == "disabled"
    assert created["id"] not in {entry["id"] for entry in visible}
    assert created["id"] in {entry["id"] for entry in all_entries}


def test_builtin_entries_cannot_be_mutated_or_disabled():
    with memory_db() as db:
        registry.seed_builtin_entries(db)
        with pytest.raises(PermissionError, match="immutable"):
            registry.update_entry(db, "client.vscode", {"status": "disabled"})
        with pytest.raises(PermissionError, match="immutable"):
            registry.disable_entry(db, "client.xcode")


def test_duplicate_custom_entry_is_rejected():
    with memory_db() as db:
        registry.create_entry(db, custom_entry(), created_by=7)
        with pytest.raises(ValueError, match="already exists"):
            registry.create_entry(db, custom_entry(), created_by=7)


def test_manifest_digest_is_deterministic_and_metadata_scoped():
    entry = custom_entry()
    digest = registry.manifest_digest({**entry, "immutable": False})
    reordered = {
        "metadata": entry["metadata"],
        "platforms": entry["platforms"],
        "capabilities": entry["capabilities"],
        **{key: value for key, value in entry.items() if key not in {"metadata", "platforms", "capabilities"}},
        "immutable": False,
    }
    assert registry.manifest_digest(reordered) == digest


def test_registry_models_reject_unsafe_entrypoints_and_urls():
    body = custom_entry()
    body["entrypoint"] = "../../run.sh"
    with pytest.raises(ValidationError, match="traversal"):
        RegistryEntryCreate(**body)

    body = custom_entry()
    body["source_url"] = "http://example.com/source"
    with pytest.raises(ValidationError, match="HTTPS"):
        RegistryEntryCreate(**body)

    with pytest.raises(ValidationError, match="At least one"):
        RegistryEntryUpdate()


def test_registry_router_is_mounted_directly_in_main_application():
    source = (Path(__file__).resolve().parents[1] / "amoscloud_ai" / "main.py").read_text(
        encoding="utf-8"
    )
    assert "registry," in source
    assert 'app.include_router(registry.router, prefix="/api/v1")' in source

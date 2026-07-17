from pathlib import Path

from fastapi.testclient import TestClient

from amoscloud_ai.codex_system_bundle import (
    BUNDLE_NAME,
    codex_system_manifest,
    create_codex_system_bundle,
)
from amoscloud_ai.main import create_app
from amoscloud_ai.mapping_bundles import MappingBundleStore


def test_codex_system_manifest_has_safe_runtime_contract():
    mappings, metadata = codex_system_manifest()

    assert metadata["kind"] == "codex-system-bundle"
    assert metadata["contains_secrets"] is False
    assert mappings["runtime"]["credential_env"] == "OPENAI_API_KEY"
    assert mappings["runtime"]["store_responses"] is False
    assert mappings["workspace"]["confined"] is True
    assert "deploy" in mappings["tools"]["approval_required"]
    assert mappings["verification"]["completion_requires_pass"] is True


def test_codex_system_bundle_round_trip(tmp_path: Path):
    store = MappingBundleStore(tmp_path)
    record = create_codex_system_bundle(store)

    assert record.name == BUNDLE_NAME
    assert record.filename.endswith(".Amosclaud.bytes")

    manifest = store.read(record.filename)
    assert manifest["metadata"]["schema"] == "amosclaud.codex-system/v1"
    assert manifest["mappings"]["agent_loop"]["stages"][-1] == "remember"


def test_codex_system_bundle_routes_require_authentication():
    client = TestClient(create_app())

    assert client.get("/api/v1/codex/system-bundle/preview").status_code == 401
    assert client.post("/api/v1/codex/system-bundle").status_code == 401
    assert client.get("/api/v1/codex/system-bundle").status_code == 401
    assert client.get("/api/v1/codex/system-bundle/download").status_code == 401

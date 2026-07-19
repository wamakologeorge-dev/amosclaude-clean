from pathlib import Path

import pytest

from amoscloud_ai.mapping_bundles import HEADER, MAGIC, MappingBundleStore


def test_amosclaud_bytes_round_trip(tmp_path: Path):
    store = MappingBundleStore(tmp_path)
    record = store.create(
        name="model-routing",
        version="1.0.0",
        mappings={"gpt-4.1-mini": {"provider": "openai"}},
        metadata={"purpose": "routing"},
    )

    path = tmp_path / record.filename
    assert path.name.endswith(".Amosclaud.bytes")
    assert path.read_bytes().startswith(MAGIC)
    assert record.byte_size == path.stat().st_size

    manifest = store.read(record.filename)
    assert manifest["schema"] == "amosclaud.mapping-bundle/v1"
    assert manifest["mappings"]["gpt-4.1-mini"]["provider"] == "openai"


def test_bundle_checksum_detects_tampering(tmp_path: Path):
    store = MappingBundleStore(tmp_path)
    record = store.create(name="demo", version="1", mappings={"a": "b"})
    path = tmp_path / record.filename
    data = bytearray(path.read_bytes())
    data[HEADER.size] ^= 1
    path.write_bytes(data)

    with pytest.raises(ValueError, match="checksum"):
        store.read(record.filename)


def test_bundle_names_are_sanitized(tmp_path: Path):
    store = MappingBundleStore(tmp_path)
    with pytest.raises(ValueError):
        store.create(name="../", version="1", mappings={})

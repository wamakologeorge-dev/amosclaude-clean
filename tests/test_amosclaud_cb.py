from pathlib import Path

from amosclaud.byte.cb import decode_packet, encode_packet
from amosclaud.core.cb.db.py.ci.api.bundle import build_default_bundle
from amosclaud.db.cb import DatabaseCB, SQLiteCBStore
from amosclaud.src.cb import discover_sources


def test_byte_cb_round_trip():
    value = {"name": "amosclaud", "ready": True}
    assert decode_packet(encode_packet(value)) == value


def test_database_cb_round_trip(tmp_path: Path):
    store = SQLiteCBStore(tmp_path / "cb.sqlite3")
    store.put(DatabaseCB("alpha", {"value": 1}))
    assert store.get("alpha") == DatabaseCB("alpha", {"value": 1})


def test_source_cb_discovers_python(tmp_path: Path):
    (tmp_path / "example.py").write_text("print('ok')\n", encoding="utf-8")
    items = discover_sources(tmp_path)
    assert items[0].path == "example.py"
    assert items[0].language == "python"


def test_bundle_manifest_verifies():
    bundle = build_default_bundle()
    manifest = bundle.manifest()
    assert bundle.verify_manifest(manifest) is True
    assert "api.describe" in manifest["capabilities"]

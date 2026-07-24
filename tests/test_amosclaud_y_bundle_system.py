import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from Amosclaud.y.bundle.system.cb import YBundleErrorCB, YBundleSystemCB


def test_y_bundle_system_builds_verifies_indexes_and_installs(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "server.py").write_text("print('Amosclaud Y')\n", encoding="utf-8")
    (source / ".env").write_text("SECRET=excluded", encoding="utf-8")
    system = YBundleSystemCB(tmp_path / "y-system")

    record = system.build(source, name="agent-server", version="1.0.0")
    assert record.bundle_id == "agent-server-1.0.0"
    assert record.files == 1
    assert system.list() == [record]
    verified = system.verify(record.bundle_id)
    assert verified["valid"] is True
    assert verified["metadata"]["system"] == "Amosclaud.y.bundle.system.cb"

    installed = system.install(record.bundle_id)
    assert (installed / "server.py").read_text(encoding="utf-8") == "print('Amosclaud Y')\n"
    assert not (installed / ".env").exists()
    assert system.status()["installed"] == 1


def test_y_bundle_system_rejects_archive_and_receipt_tampering(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "data.txt").write_text("verified", encoding="utf-8")
    system = YBundleSystemCB(tmp_path / "y-system")
    archive_record = system.build(source, name="archive", version="1")
    archive = system.archives / archive_record.archive
    archive.write_bytes(archive.read_bytes() + b"tampered")
    with pytest.raises(YBundleErrorCB, match="archive checksum"):
        system.verify(archive_record.bundle_id)

    receipt_system = YBundleSystemCB(tmp_path / "receipt-system")
    receipt_record = receipt_system.build(source, name="receipt", version="1")
    receipt = receipt_system.receipts / f"{receipt_record.bundle_id}.cb.json"
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    payload["version"] = "changed"
    receipt.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(YBundleErrorCB, match="receipt checksum"):
        receipt_system.verify(receipt_record.bundle_id)


def test_y_bundle_safe_extraction_rejects_zip_slip(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "safe.txt").write_text("safe", encoding="utf-8")
    system = YBundleSystemCB(tmp_path / "y-system")
    record = system.build(source, name="unsafe-test", version="1")
    archive = system.archives / record.archive
    manifest = None
    with zipfile.ZipFile(archive) as current:
        manifest = current.read("AMOSCLAUD_BUNDLE_MANIFEST.json")
        safe_content = current.read("safe.txt")
    with zipfile.ZipFile(archive, "w") as changed:
        changed.writestr("safe.txt", safe_content)
        changed.writestr("../escape.txt", "escape")
        changed.writestr("AMOSCLAUD_BUNDLE_MANIFEST.json", manifest)
    data = archive.read_bytes()
    index = json.loads(system.index_path.read_text(encoding="utf-8"))
    index["bundles"][record.bundle_id]["archive_sha256"] = hashlib.sha256(data).hexdigest()
    unsigned = dict(index["bundles"][record.bundle_id])
    unsigned.pop("receipt_sha256")
    receipt = system._receipt(unsigned)
    index["bundles"][record.bundle_id] = receipt
    system._write_index(index)
    receipt_path = system.receipts / f"{record.bundle_id}.cb.json"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(YBundleErrorCB):
        system.install(record.bundle_id)
    assert not (tmp_path / "escape.txt").exists()

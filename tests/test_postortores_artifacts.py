from pathlib import Path

import pytest

from postortores.artifacts import ArtifactStore
from postortores.snapshot import SnapshotManager
from postortores.engine import PostortoresEngine
from postortores.types import DataRecord


def test_artifact_store_deduplicates_and_verifies(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    first = store.put(b"same-build-output", media_type="text/plain", labels={"kind": "build"})
    second = store.put(b"same-build-output", media_type="text/plain", labels={"kind": "build"})
    assert first["digest"] == second["digest"]
    assert store.get(first["digest"]) == b"same-build-output"
    assert store.verify(first["digest"]) is True


def test_artifact_store_detects_tampering(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    meta = store.put(b"verified")
    object_path = store._object_path(meta["digest"])
    object_path.write_bytes(b"tampered")
    assert store.verify(meta["digest"]) is False
    with pytest.raises(IOError):
        store.get(meta["digest"])


def test_snapshot_roundtrip_preserves_postortores_state(tmp_path: Path) -> None:
    source_path = tmp_path / "source.db"
    engine = PostortoresEngine(source_path)
    engine.put(DataRecord(namespace="agent", key="task", value={"status": "verified"}))
    engine.close()

    manager = SnapshotManager(source_path)
    snapshot = tmp_path / "backup.postortores"
    manifest = manager.create(snapshot)
    assert manifest["format"] == "amosclaud-postortores-snapshot-v1"
    assert manager.verify(snapshot) is True

    restored_path = tmp_path / "restored.db"
    manager.restore(snapshot, restored_path)
    restored = PostortoresEngine(restored_path)
    record = restored.get("agent", "task")
    restored.close()
    assert record is not None
    assert record.value == {"status": "verified"}

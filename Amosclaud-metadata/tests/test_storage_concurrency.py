from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from amosclaud_metadata import JsonMetadataStore, MetadataEnvelope


def test_concurrent_duplicate_writes_preserve_one_record(tmp_path: Path) -> None:
    store = JsonMetadataStore(tmp_path)
    envelope = MetadataEnvelope(
        record_type="health",
        payload={"component": "metadata-store", "status": "healthy"},
        record_id="fixed-record-id",
        created_at="2026-07-16T00:00:00+00:00",
    )

    def append_once() -> str:
        try:
            return str(store.append(envelope))
        except FileExistsError:
            return "duplicate"

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _: append_once(), range(8)))

    assert len(store.list_records("health")) == 1
    assert results.count("duplicate") == 7
    assert len([result for result in results if result != "duplicate"]) == 1
    assert not list(tmp_path.rglob("*.tmp"))

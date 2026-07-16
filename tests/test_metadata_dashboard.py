from __future__ import annotations

import json
from pathlib import Path

from amoscloud_ai.api.routes import metadata_dashboard
from amoscloud_ai.main import app


def test_metadata_loader_summarizes_records(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("AMOSCLAUD_METADATA_PATH", str(tmp_path))
    record = {
        "id": "run-42",
        "type": "autonomous-run",
        "title": "Verify agent chain",
        "status": "success",
        "created_at": "2026-07-16T12:00:00+00:00",
        "source": "Amosclaud Autonomous",
    }
    (tmp_path / "run.json").write_text(json.dumps(record), encoding="utf-8")

    records, invalid = metadata_dashboard._load_records()

    assert invalid == []
    assert records == [
        {
            "id": "run-42",
            "type": "autonomous-run",
            "title": "Verify agent chain",
            "status": "success",
            "timestamp": "2026-07-16T12:00:00+00:00",
            "source": "Amosclaud Autonomous",
            "path": "run.json",
        }
    ]


def test_metadata_loader_reports_invalid_json(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("AMOSCLAUD_METADATA_PATH", str(tmp_path))
    (tmp_path / "broken.json").write_text("{not-json", encoding="utf-8")

    records, invalid = metadata_dashboard._load_records()

    assert records == []
    assert invalid == ["broken.json"]


def test_metadata_api_is_registered_through_agent_chain() -> None:
    paths = {route.path for route in app.routes}
    assert "/api/v1/agent-chain/metadata/summary" in paths

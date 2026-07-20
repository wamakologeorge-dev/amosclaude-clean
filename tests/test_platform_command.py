from __future__ import annotations

import json
from pathlib import Path

from amosclaud_platform.control import PlatformControl


def test_platform_control_initializes_shared_services(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(Path(__file__).resolve().parents[1])
    monkeypatch.setenv("AMOSCLAUD_PLATFORM_DATABASE_URL", f"sqlite:///{tmp_path / 'platform.db'}")
    monkeypatch.setenv("AMOSCLAUD_REPOSITORIES_ROOT", str(tmp_path / "repositories"))
    monkeypatch.setenv("AMOSCLAUD_BYTE_BUS_SECRET", "x" * 32)
    monkeypatch.setattr(
        PlatformControl,
        "IMPORT_CHECKS",
        {
            "database": "database.session",
            "repository": "repository.connector",
            "agent_worker": "agents.codex_agent",
        },
    )

    report = PlatformControl().doctor()

    assert report.healthy is True
    assert report.status == "ready"
    services = {item.name: item for item in report.services}
    assert services["shared_database"].status == "ready"
    assert services["repository_storage"].status == "ready"
    assert services["agent_manifest"].status == "ready"
    assert services["byte_bus_secret"].status == "ready"
    parsed = json.loads(report.render())
    assert parsed["healthy"] is True


def test_platform_control_reports_optional_bus_secret_warning(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(Path(__file__).resolve().parents[1])
    monkeypatch.setenv("AMOSCLAUD_PLATFORM_DATABASE_URL", f"sqlite:///{tmp_path / 'platform.db'}")
    monkeypatch.setenv("AMOSCLAUD_REPOSITORIES_ROOT", str(tmp_path / "repositories"))
    monkeypatch.delenv("AMOSCLAUD_BYTE_BUS_SECRET", raising=False)
    monkeypatch.setattr(PlatformControl, "IMPORT_CHECKS", {"database": "database.session"})

    report = PlatformControl().status()

    services = {item.name: item for item in report.services}
    assert report.healthy is True
    assert services["byte_bus_secret"].status == "warning"
    assert services["byte_bus_secret"].required is False

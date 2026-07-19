from pathlib import Path

from amoscloud_ai.Amosclaud import AmosclaudDashboard
from amoscloud_ai.core.workspace import WorkspaceEngine


def test_metadata_dashboard_reports_platform_without_secret_values(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("AMOSCLAUD_ACCESS_MODE", "local")
    monkeypatch.setenv("AMOSCLAUD_PUBLIC_DOMAIN", "amosclaud.com")
    monkeypatch.setenv("AMOSCLAUD_MODEL", "test-model")
    monkeypatch.setenv("AMOSCLAUD_MASTER_KEY", "must-never-appear")
    monkeypatch.setenv("AMOSCLAUD_VISIBLE_SETTING", "enabled")

    dashboard = AmosclaudDashboard(WorkspaceEngine(tmp_path / "workspace"))
    snapshot = dashboard.snapshot()

    assert snapshot["identity"]["runtime"] == "Amosclaud.py"
    assert snapshot["agent"]["language"] == "Amo Runtime"
    assert snapshot["network"]["access_mode"] == "local"
    assert snapshot["workspace"]["manifest"]["source_of_truth"] == "files"
    assert snapshot["configuration"]["secrets_redacted"] is True
    assert "AMOSCLAUD_VISIBLE_SETTING" in snapshot["configuration"]["visible_variable_names"]
    assert "AMOSCLAUD_MASTER_KEY" not in snapshot["configuration"]["visible_variable_names"]
    assert "must-never-appear" not in str(snapshot)


def test_metadata_dashboard_lists_expected_capabilities(tmp_path: Path):
    snapshot = AmosclaudDashboard(WorkspaceEngine(tmp_path / "workspace")).snapshot()

    assert snapshot["capabilities"]["folder_first_workspace"] is True
    assert snapshot["capabilities"]["amo_runtime"] is True
    assert snapshot["capabilities"]["local_agent"] is True
    assert snapshot["storage"]["workspace_disk"]["total_bytes"] > 0

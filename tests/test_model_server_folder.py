from pathlib import Path

from amoscloud_ai.api.routes import model_server_folder


def test_model_server_folder_starts_at_zero_without_layout(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("AMOSCLAUD_MODEL_SERVER_ROOT", str(tmp_path / "model-server"))
    monkeypatch.setattr(model_server_folder.model_network, "network_status", lambda: {"configured": False, "ready_stations": 0})
    result = model_server_folder.status_payload()
    assert result["progress_percent"] == 0
    assert result["stage"] == "folder-posted"
    assert result["public_home"] == "https://www.amosclaud.com"


def test_wake_builds_one_hundred_logical_engines(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("AMOSCLAUD_MODEL_SERVER_ROOT", str(tmp_path / "model-server"))
    monkeypatch.setattr(model_server_folder.model_network, "network_status", lambda: {"configured": False, "ready_stations": 0})
    result = model_server_folder.wake_model_server_folder(model_server_folder.WakeRequest())
    assert result["progress_percent"] == 25
    assert result["logical_engines"] == 100
    assert (tmp_path / "model-server" / "engines" / "engine-100").is_dir()


def test_network_progress_reaches_live(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("AMOSCLAUD_MODEL_SERVER_ROOT", str(tmp_path / "model-server"))
    model_server_folder._safe_create_layout(100)
    monkeypatch.setattr(model_server_folder.model_network, "network_status", lambda: {"configured": True, "ready_stations": 1, "ready": True})
    result = model_server_folder.status_payload()
    assert result["progress_percent"] == 100
    assert result["stage"] == "live"

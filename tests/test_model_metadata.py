import json
from pathlib import Path

import pytest

from amosclaud_model.metadata import (
    ModelMetadataError,
    load_model_metadata,
    runtime_model_metadata,
    validate_model_metadata,
)


def test_packaged_model_metadata_is_complete_and_secret_free():
    metadata = load_model_metadata()
    assert metadata["model_id"] == "amosclaud-folder-v1"
    assert "amosclaud-api-key" in metadata["authentication"]
    assert metadata["data_policy"]["stores_api_keys"] is False
    assert "api_key" not in metadata


def test_workspace_metadata_override_is_supported(tmp_path: Path):
    packaged = load_model_metadata()
    packaged["version"] = "1.0.1-test"
    config = tmp_path / "config"
    config.mkdir()
    (config / "model_metadata.json").write_text(json.dumps(packaged), encoding="utf-8")
    assert load_model_metadata(tmp_path)["version"] == "1.0.1-test"


def test_runtime_metadata_reports_checkpoint_without_changing_source(tmp_path: Path):
    checkpoint = tmp_path / "checkpoints" / "current.json"
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_text("{}", encoding="utf-8")
    metadata = runtime_model_metadata(tmp_path, runtime="folder-native", ready=True)
    assert metadata["runtime"] == {
        "engine": "folder-native",
        "ready": True,
        "checkpoint_available": True,
    }
    assert "runtime" not in load_model_metadata()


def test_metadata_rejects_embedded_credentials():
    metadata = load_model_metadata()
    metadata["deployment"] = {"api_key": "must-never-be-recorded"}
    with pytest.raises(ModelMetadataError, match="deployment.api_key"):
        validate_model_metadata(metadata)

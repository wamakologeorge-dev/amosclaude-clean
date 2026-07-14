import json
import time

from amosclaud_model.config import ModelConfig
from amosclaud_model.training_service import TrainingService, audit_dataset_licenses
from amosclaud_model.workspace import initialize


def _licensed_workspace(tmp_path):
    root = tmp_path / "model"
    initialize(root, ModelConfig(order=2, temperature=0))
    (root / "datasets" / "curated" / "train.txt").write_text(
        "inspect change run tests report evidence", encoding="utf-8"
    )
    record = {"id": "owned-1", "dataset": "curated", "license": "project-owned"}
    (root / "datasets" / "manifest.jsonl").write_text(json.dumps(record) + "\n")
    return root


def test_training_service_persists_completed_job(tmp_path):
    root = _licensed_workspace(tmp_path)
    service = TrainingService(root)
    submitted = service.submit("train")
    for _ in range(100):
        job = service.get(submitted["id"])
        if job["status"] in {"completed", "failed"}:
            break
        time.sleep(0.01)
    assert job["status"] == "completed"
    assert job["result"]["documents"] == 1
    assert TrainingService(root).get(job["id"])["status"] == "completed"


def test_training_rejects_unverified_dataset_rights(tmp_path):
    root = _licensed_workspace(tmp_path)
    manifest = root / "datasets" / "manifest.jsonl"
    manifest.write_text(json.dumps({"id": "bad", "dataset": "unknown", "license": "unverified"}))
    audit = audit_dataset_licenses(root)
    assert audit["approved"] is False
    assert audit["invalid"][0]["license"] == "unverified"
    try:
        TrainingService(root).submit("train")
        assert False, "unlicensed training should fail"
    except ValueError as error:
        assert "license audit failed" in str(error)


def test_amosclaud_training_agreement_labels_are_approved(tmp_path):
    root = _licensed_workspace(tmp_path)
    manifest = root / "datasets" / "manifest.jsonl"
    manifest.write_text(
        json.dumps(
            {
                "id": "contributor-1",
                "dataset": "contribution",
                "license": "amosclaud-contributor-license-1.0",
            }
        )
        + "\n"
    )
    assert audit_dataset_licenses(root)["approved"] is True

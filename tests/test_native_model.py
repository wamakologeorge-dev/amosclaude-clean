import json

import pytest
from fastapi.testclient import TestClient

from amosclaud_model.config import ModelConfig
from amosclaud_model.model import FolderLanguageModel, detokenize, tokenize
from amosclaud_model.workspace import import_folder, initialize


def test_folder_model_trains_and_generates_without_api_key(tmp_path):
    root = tmp_path / "model"
    initialize(root, ModelConfig(order=3, max_tokens=30, temperature=0))
    curated = root / "datasets" / "curated" / "train.jsonl"
    curated.write_text(
        json.dumps({"text": "<user> verify patch <assistant> run tests and inspect logs"}) + "\n",
        encoding="utf-8",
    )
    model = FolderLanguageModel(root)
    result = model.train()
    assert result["documents"] == 1
    assert result["tokens"] > 5
    assert model.checkpoint_path.exists()
    assert (root / "tokenizer" / "vocab.json").exists()
    assert model.generate("<user> verify patch <assistant>", max_tokens=8)


def test_import_folder_filters_binary_secrets_and_dependencies(tmp_path):
    root = tmp_path / "model"
    initialize(root)
    source = tmp_path / "project"
    source.mkdir()
    (source / "main.py").write_text("print('safe')", encoding="utf-8")
    (source / "secret.key").write_text("private", encoding="utf-8")
    (source / "node_modules").mkdir()
    (source / "node_modules" / "dependency.js").write_text("ignored", encoding="utf-8")
    result = import_folder(root, source, "project-owned")
    assert result["files"] == 1
    assert result["license"] == "project-owned"
    assert len(result["content_sha256"]) == 64
    assert (root / "datasets" / "raw" / "project" / "main.py").exists()
    assert not (root / "datasets" / "raw" / "project" / "secret.key").exists()


def test_tokenizer_round_trip_is_readable():
    tokens = tokenize("def build(value):\nreturn value + 1")
    assert "def" in tokens and "return" in tokens
    assert "return value + 1" in detokenize(tokens)


def test_training_requires_corpus(tmp_path):
    root = tmp_path / "model"
    initialize(root)
    with pytest.raises(ValueError, match="No training documents"):
        FolderLanguageModel(root).train()


def test_openai_compatible_server_uses_local_checkpoint(tmp_path, monkeypatch):
    root = tmp_path / "model"
    initialize(root, ModelConfig(order=2, temperature=0))
    (root / "datasets" / "curated" / "train.txt").write_text(
        "<user> test <assistant> verified locally", encoding="utf-8"
    )
    FolderLanguageModel(root).train()
    monkeypatch.setenv("AMOSCLAUD_MODEL_HOME", str(root))
    monkeypatch.setenv("AMOSCLAUD_MODEL_TOKEN", "private-model-token")
    from amosclaud_model.server import create_app

    with TestClient(create_app()) as client:
        assert client.get("/health").json()["status"] == "ready"
        assert client.get("/v1/models").status_code == 401
        response = client.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer private-model-token"},
            json={
                "model": "amosclaud-folder-v1",
                "messages": [{"role": "user", "content": "test"}],
            },
        )
        assert response.status_code == 200
        assert response.json()["amosclaud"]["runtime"] == "folder-native"
        assert response.json()["choices"][0]["message"]["content"]
        logs = client.get("/v1/logs", headers={"Authorization": "Bearer private-model-token"})
        assert logs.status_code == 200
        assert logs.json()["data"][0]["event"] == "inference.completed"
        assert client.get("/v1/logs/verify").status_code == 401
        verified = client.get(
            "/v1/logs/verify", headers={"Authorization": "Bearer private-model-token"}
        )
        assert verified.json()["valid"] is True
        assert client.get("/v1/training/licenses").status_code == 401
        licenses = client.get(
            "/v1/training/licenses",
            headers={"Authorization": "Bearer private-model-token"},
        )
        assert licenses.status_code == 200
        assert licenses.json()["approved"] is False


def test_native_model_accepts_amosclaud_api_key(tmp_path, monkeypatch):
    root = tmp_path / "model"
    initialize(root)
    monkeypatch.setenv("AMOSCLAUD_MODEL_HOME", str(root))
    monkeypatch.delenv("AMOSCLAUD_MODEL_TOKEN", raising=False)
    monkeypatch.setenv("AMOSCLAUD_API_KEY", "amos_native_test_key")
    from amosclaud_model.server import create_app

    with TestClient(create_app()) as client:
        assert client.get("/v1/models").status_code == 401
        assert (
            client.get(
                "/v1/models", headers={"Authorization": "Bearer amos_native_test_key"}
            ).status_code
            == 200
        )
        assert (
            client.get("/v1/models", headers={"X-API-Key": "amos_native_test_key"}).status_code
            == 200
        )


def test_versioned_checkpoints_evaluate_promote_and_rollback(tmp_path):
    root = tmp_path / "model"
    initialize(root, ModelConfig(order=2, temperature=0))
    train = root / "datasets" / "curated" / "train.txt"
    train.write_text("inspect patch run focused tests", encoding="utf-8")
    (root / "datasets" / "eval" / "held-out.txt").write_text(
        "inspect patch run tests", encoding="utf-8"
    )
    model = FolderLanguageModel(root)
    first = model.train()
    assert first["metrics"]["documents"] == 1
    assert first["metrics"]["perplexity"] > 0
    train.write_text(
        "inspect patch run focused tests\nreview logs report evidence", encoding="utf-8"
    )
    second = model.train()
    assert second["checkpoint_id"] != first["checkpoint_id"]
    assert len(model.checkpoints()) == 2
    rolled_back = model.rollback()
    assert rolled_back["checkpoint_id"] == first["checkpoint_id"]
    promoted = model.promote(second["checkpoint_id"])
    assert promoted["checkpoint_id"] == second["checkpoint_id"]


def test_checkpoint_integrity_blocks_tampering(tmp_path):
    root = tmp_path / "model"
    initialize(root)
    (root / "datasets" / "curated" / "train.txt").write_text("safe training data", encoding="utf-8")
    model = FolderLanguageModel(root)
    checkpoint = model.train()
    version = root / "checkpoints" / "versions" / f"{checkpoint['checkpoint_id']}.json"
    version.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="integrity"):
        model.promote(checkpoint["checkpoint_id"])

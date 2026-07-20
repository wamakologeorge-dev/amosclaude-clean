from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "model-workspace" / "Dockerfile"
STARTER = ROOT / "model-workspace" / "start-model.sh"
COMPOSE = ROOT / "Infrastructure" / "docker-compose.yml"


def test_model_workspace_runs_as_non_root_governed_service() -> None:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    assert "USER amosclaud" in dockerfile
    assert 'VOLUME ["/model"]' in dockerfile
    assert 'ENTRYPOINT ["/app/start-model.sh"]' in dockerfile
    assert "uvicorn" not in dockerfile.lower()
    assert "FastAPI(" not in dockerfile


def test_model_startup_validates_rights_and_checkpoint() -> None:
    starter = STARTER.read_text(encoding="utf-8")
    assert "model_metadata.json" in starter
    assert "license-audit" in starter
    assert "amosclaud-model train" in starter
    assert "amosclaud-model evaluate" in starter
    assert "checkpoints/current.json" in starter
    assert "exec amosclaud-model serve" in starter


def test_model_workspace_cooperates_with_unified_platform_compose() -> None:
    compose = COMPOSE.read_text(encoding="utf-8")
    assert "dockerfile: model-workspace/Dockerfile" in compose
    assert "AMOSCLAUD_MODEL_URL: http://model:8091" in compose
    assert "AMOSCLAUD_MODEL_HEALTH_URL: http://model:8091/health" in compose
    assert "- amosclaud-model:/model" in compose
    assert "- amosclaud-model:/model:ro" in compose

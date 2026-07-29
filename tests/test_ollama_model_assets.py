from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODEL_NAME = "wamakologeorge/amosclaud-clean:latest"


def test_modelfile_builds_amosclaud_from_llama32():
    modelfile = (ROOT / "models" / "ollama" / "Modelfile").read_text(
        encoding="utf-8"
    )

    assert "FROM llama3.2" in modelfile
    assert "SYSTEM" in modelfile
    assert "Amosclaud Autonomous" in modelfile
    assert "Never reveal credentials" in modelfile


def test_publish_script_creates_tests_and_pushes_namespaced_model():
    script = (ROOT / "scripts" / "publish_ollama_model.sh").read_text(
        encoding="utf-8"
    )

    assert MODEL_NAME in script
    assert 'ollama pull "$BASE_MODEL"' in script
    assert 'ollama create "$MODEL_NAME" -f "$MODELFILE"' in script
    assert 'ollama run "$MODEL_NAME"' in script
    assert 'ollama push "$MODEL_NAME"' in script
    assert "AMOSCLAUD_MODEL_READY" in script


def test_manual_workflow_verifies_published_model_with_repository_secret():
    workflow = (
        ROOT / ".github" / "workflows" / "ollama-model-verify.yml"
    ).read_text(encoding="utf-8")

    for required in (
        MODEL_NAME,
        "workflow_dispatch:",
        "OLLAMA_API_KEY: ${{ secrets.OLLAMA_API_KEY }}",
        "OLLAMA_REQUIRE_MODEL: 'true'",
        "OLLAMA_PROBE_COMPLETION: 'true'",
        "python -m amosclaud_bot.ollama_connection",
    ):
        assert required in workflow


def test_model_agent_uses_same_selected_ollama_model_for_preflight_and_inference():
    workflow = (
        ROOT / ".github" / "workflows" / "amosclaud-model-agent.yml"
    ).read_text(encoding="utf-8")

    assert workflow.count("vars.AMOSCLAUD_MODEL || vars.OLLAMA_MODEL") == 2
    assert "OLLAMA_REQUIRE_MODEL: 'true'" in workflow
    assert (
        "AMOSCLAUD_MODEL_TOKEN: ${{ secrets.AMOSCLAUD_MODEL_TOKEN || secrets.OLLAMA_API_KEY"
        in workflow
    )

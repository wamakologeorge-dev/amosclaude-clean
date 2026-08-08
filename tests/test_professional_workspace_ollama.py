from pathlib import Path

from amoscloud_ai.ollama_compat import apply_ollama_environment

ROOT = Path(__file__).resolve().parents[1]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_terminal_agent_hub_supports_read_only_access() -> None:
    source = _source("amoscloud_ai/api/routes/cloud_workspaces.py")
    hub = source.split('@router.get("/repositories/{repository_id}/agent-hub")', 1)[1]
    get_handler, post_handler = hub.split(
        '@router.post("/repositories/{repository_id}/agent-hub/messages")', 1
    )

    assert '"access": {' in get_handler
    assert '"can_write": can_write' in get_handler
    assert '"write_available": bool(can_write and spec["write_capable"])' in get_handler
    assert "_require_write(repository)" not in get_handler
    assert "if changes_authorized:" in post_handler
    assert "_require_write(repository)" in post_handler


def test_model_planning_requires_write_only_for_fix_mode() -> None:
    source = _source("amosclaud_os/agent/executor.py")
    model_section = source.split("# A general build or repair requires", 1)[1]

    assert "execution_mode = (" in model_section
    assert 'if execution_mode == "fix":' in model_section
    assert "repositories._require_write(access)" in model_section
    assert 'authorized_writes=role in {"owner", "developer"}' in model_section
    assert "Configure AMOSCLAUD_MODEL_URL or OLLAMA_URL" in model_section


def test_terminal_mobile_deep_link_and_access_ui_are_connected() -> None:
    loader = _source("web/cloud-workspace.js")
    hub = _source("web/cloud-terminal/agent-hub.js")
    mobile = _source("web/cloud-terminal/mobile.css")

    assert "location.hash !== '#terminal'" in loader
    assert '.ws-tab[data-tab="terminal"]' in loader
    assert "script.addEventListener('load'" in loader
    assert "/static/cloud-terminal/mobile.css" in loader
    assert "payload.access?.can_write" in hub
    assert "planning and diagnosis only for this repository role" in hub
    assert "min-height: 55svh" in mobile
    assert "min-height: 48px" in mobile


def test_legacy_agent_exposes_live_ollama_controls() -> None:
    page = _source("web/index.html")
    controls = _source("web/amomodel-controls.js")
    production = _source("amoscloud_ai/production_app.py")

    assert 'id="amomodel-controls"' in page
    assert 'id="amomodel-status"' in page
    assert "configured Ollama model" in page
    assert "/api/v1/amomodel/model/status" in controls
    assert "Ollama connected" in controls
    assert "apply_ollama_environment()" in production


def test_ollama_environment_maps_protected_server_variables() -> None:
    environment = {
        "OLLAMA_URL": "https://ollama.example/v1/chat/completions",
        "OLLAMA_API_KEY": "protected-test-value",
        "OLLAMA_MODEL": "gpt-oss:120b",
    }

    report = apply_ollama_environment(environment)

    assert environment["AMOSCLAUD_MODEL_URL"] == "https://ollama.example"
    assert environment["AMOSCLAUD_MODEL_COMPLETIONS_PATH"] == "/v1/chat/completions"
    assert environment["AMOSCLAUD_MODEL_TOKEN"] == "protected-test-value"
    assert environment["AMOSCLAUD_MODEL"] == "gpt-oss:120b"
    assert report["ollama_configured"] is True
    assert report["credential_configured"] is True
    assert "protected-test-value" not in repr(report)


def test_existing_amosclaud_model_settings_take_precedence() -> None:
    environment = {
        "OLLAMA_URL": "https://ollama.example",
        "OLLAMA_API_KEY": "ollama-secret",
        "OLLAMA_MODEL": "ollama-model",
        "AMOSCLAUD_MODEL_URL": "https://model.amosclaud.internal",
        "AMOSCLAUD_MODEL_TOKEN": "amosclaud-secret",
        "AMOSCLAUD_MODEL": "amosclaud-model",
    }

    apply_ollama_environment(environment)

    assert environment["AMOSCLAUD_MODEL_URL"] == "https://model.amosclaud.internal"
    assert environment["AMOSCLAUD_MODEL_TOKEN"] == "amosclaud-secret"
    assert environment["AMOSCLAUD_MODEL"] == "amosclaud-model"

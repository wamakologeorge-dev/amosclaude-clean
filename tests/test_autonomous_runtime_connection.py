from pathlib import Path

from amoscloud_ai.main import create_app
from src.agent.model import load_model_config


def test_autonomous_model_can_use_railway_bot_service(monkeypatch):
    for name in (
        "AMOSCLAUD_MODEL_ENDPOINT",
        "AMOSCLAUD_MODEL_URL",
        "AMOSCLAUD_API_URL",
        "AMOSCLAUD_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AMOSCLAUD_BOT_URL", "http://amosclaud-bot.railway.internal:8080/")
    monkeypatch.setenv("AMOSCLAUD_BOT_COMPLETIONS_PATH", "v1/chat/completions")
    monkeypatch.setenv("AMOSCLAUD_BOT_TOKEN", "shared-service-token")
    monkeypatch.setenv("AMOSCLAUD_MODEL", "amosclaud-agent")

    config = load_model_config()

    assert config.endpoint == "http://amosclaud-bot.railway.internal:8080"
    assert config.provider == "amosclaud-bot"
    assert config.completions_path == "/v1/chat/completions"
    assert config.api_key == "shared-service-token"


def test_autonomous_model_status_route_is_registered():
    paths = {getattr(route, "path", "") for route in create_app().routes}
    assert "/api/v1/amomodel/model/status" in paths


def test_repository_page_loads_github_import_and_selects_project_context():
    repositories_script = Path("web/repositories.js").read_text(encoding="utf-8")
    github_script = Path("web/github-repositories.js").read_text(encoding="utf-8")

    assert "/static/github-repositories.js" in repositories_script
    assert "/api/v1/core/os/context" in repositories_script
    assert "amosclaud.activeProjectContext" in repositories_script
    assert "/api/v1/core/os/context" in github_script
    assert "imported and selected for Amosclaud Agent" in github_script


def test_agent_page_uses_real_runtime_readiness():
    html = Path("web/index.html").read_text(encoding="utf-8")
    script = Path("web/runtime-readiness.js").read_text(encoding="utf-8")

    assert "/static/runtime-readiness.js" in html
    assert "/api/v1/amomodel/model/status" in script
    assert "/api/v1/core/os/context" in script
    assert "Autonomous blocker:" in script


def test_autonomous_gateway_delegates_to_shared_native_provider(monkeypatch):
    from amoscloud_ai.model_api_response import ModelApiResponse
    from src.agent import model as autonomous_model

    captured = {}

    def native_reply(history, system_prompt):
        captured["history"] = history
        captured["system_prompt"] = system_prompt
        return ModelApiResponse(
            reply='{"plan": [], "changes": [], "commit_message": "none"}',
            runtime="self-hosted",
            status="ready",
            provider="amosclaud",
            model="amosclaud-coder",
        )

    monkeypatch.setattr(autonomous_model.native_provider, "reply", native_reply)
    gateway = autonomous_model.AutonomousModelGateway()

    response = gateway.complete("Update the selected repository", ["Repository tree inspected"])

    assert response.startswith('{"plan"')
    assert captured["history"][0]["role"] == "user"
    assert "Update the selected repository" in captured["history"][0]["content"]

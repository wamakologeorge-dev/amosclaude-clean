from __future__ import annotations

import json
from pathlib import Path

from amosclaud_bot import model_agent
from amoscloud_ai.model_api_response import ModelApiResponse


def _event(tmp_path: Path, *, body: str, association: str = "OWNER") -> Path:
    path = tmp_path / "event.json"
    path.write_text(
        json.dumps(
            {
                "comment": {
                    "body": body,
                    "author_association": association,
                },
                "issue": {"number": 17},
            }
        ),
        encoding="utf-8",
    )
    return path


def _install_environment(monkeypatch, event_path: Path) -> None:
    monkeypatch.setenv("GITHUB_EVENT_NAME", "issue_comment")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_TOKEN", "github-token")


def test_model_command_has_a_separate_non_conflicting_prefix():
    command = model_agent.parse_model_command("/amosclaud ask explain this failure")
    assert command.name == "ask"
    assert command.prompt == "explain this failure"
    assert model_agent.parse_model_command("/amosclaud model status").name == "status"
    assert model_agent.parse_model_command("@amosclaud ask duplicate route").name is None


def test_untrusted_comment_cannot_consume_model_credentials(tmp_path, monkeypatch):
    event = _event(
        tmp_path,
        body="/amosclaud ask explain the repository",
        association="NONE",
    )
    _install_environment(monkeypatch, event)
    comments: list[str] = []
    monkeypatch.setattr(
        model_agent,
        "_post_comment",
        lambda _repo, _number, body, _token: comments.append(body),
    )
    monkeypatch.setattr(
        model_agent.provider,
        "reply",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("provider must not run for an untrusted comment")
        ),
    )

    assert model_agent.run_from_environment() == 0
    assert comments and "Model request blocked" in comments[0]


def test_trusted_comment_returns_real_provider_metadata(tmp_path, monkeypatch):
    event = _event(tmp_path, body="/amosclaud ask what should I verify first?")
    _install_environment(monkeypatch, event)
    comments: list[str] = []
    monkeypatch.setattr(
        model_agent,
        "_post_comment",
        lambda _repo, _number, body, _token: comments.append(body),
    )
    monkeypatch.setattr(
        model_agent.provider,
        "reply",
        lambda history, system_prompt: ModelApiResponse(
            reply="Run the smallest relevant test first.",
            runtime="external-adapter:anthropic",
            provider="anthropic",
            model="test-model",
        ),
    )

    assert model_agent.run_from_environment() == 0
    assert len(comments) == 1
    assert "Run the smallest relevant test first." in comments[0]
    assert "external-adapter:anthropic" in comments[0]
    assert "No repository change was made" in comments[0]


def test_workflow_wires_first_party_ollama_and_fallback_secret_names():
    workflow = (
        Path(__file__).resolve().parents[1] / ".github" / "workflows" / "amosclaud-model-agent.yml"
    ).read_text(encoding="utf-8")

    for required in (
        "secrets.GITHUB_TOKEN",
        "secrets.AMOSCLAUD_API_KEY",
        "secrets.AMOSCLAUD_MODEL_URL",
        "secrets.OLLAMA_URL",
        "secrets.AMOSCLAUD_MODEL_TOKEN",
        "OLLAMA_API_KEY: ${{ secrets.OLLAMA_API_KEY }}",
        "secrets.OLLAMA_CLOUD_API_KEY",
        "secrets.OLLAMA_KEY",
        "secrets.OLLAMA_TOKEN",
        "secrets.AMOSCLAUD_OLLAMA_API_KEY",
        "secrets.OLLAMA",
        "'https://ollama.com'",
        "'gpt-oss:120b'",
        "secrets.ANTHROPIC_API_KEY",
        "secrets.OPENAI_API_KEY",
        "AMOSCLAUD_ALLOW_EXTERNAL_ADAPTERS: 'true'",
        "python -m amosclaud_bot.ollama_connection",
        "python -m amosclaud_bot.model_agent",
    ):
        assert required in workflow

    assert "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1" in workflow
    assert "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97" in workflow

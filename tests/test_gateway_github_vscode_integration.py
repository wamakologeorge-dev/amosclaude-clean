"""Contracts for the gateway, Responses API, and GitHub operation sync."""

from pathlib import Path


def test_openai_gateway_supports_responses_without_removing_chat() -> None:
    source = Path("amoscloud_ai/api/routes/openai_compat.py").read_text(encoding="utf-8")

    assert '@router.post("/chat/completions")' in source
    assert '@router.post("/responses")' in source
    assert '"object": "response"' in source
    assert '"output_text": reply' in source
    assert "agent_request_refund" in source
    assert "store=False" in source
    assert "Streaming is not enabled" in source


def test_github_sync_uses_the_governed_task_gateway() -> None:
    workflow = Path(".github/workflows/amosclaud-agent-sync.yml").read_text(encoding="utf-8")
    script = Path(".github/scripts/amosclaud_agent_sync.py").read_text(encoding="utf-8")

    assert "workflow_dispatch:" in workflow
    assert "repository_dispatch:" in workflow
    assert "secrets.AMOSCLAUD_API_KEY" in workflow
    assert "persist-credentials: false" in workflow
    assert "/api/v1/tasks" in script
    assert '"require_approval"' in script
    assert '"github_run_id"' in script
    assert '"Authorization": f"Bearer {api_key}"' in script
    assert "print(api_key" not in script


def test_continue_and_integration_docs_point_to_one_public_gateway() -> None:
    config = Path("config/continue/amosclaud.yaml.example").read_text(encoding="utf-8")
    guide = Path("docs/GATEWAY_GITHUB_VSCODE_INTEGRATION.md").read_text(encoding="utf-8")

    assert "apiBase: https://www.amosclaud.com/v1" in config
    assert "useResponsesApi: true" in config
    assert "https://www.amosclaud.com/mcp/" in guide
    assert "operation bucket" in guide.lower()
    assert "Do not deploy a second public control plane" in guide

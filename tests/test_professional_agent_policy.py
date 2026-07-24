from pathlib import Path

from amoscloud_ai.api.routes import chat
from amoscloud_ai.professionalism import PROFESSIONAL_AGENT_POLICY


def test_shared_policy_requires_evidence_and_secret_protection():
    policy = PROFESSIONAL_AGENT_POLICY.lower()
    assert "never claim" in policy
    assert "first-party action or tool result confirms it" in policy
    assert "do not expose secrets" in policy
    assert "completed work, work in progress" in policy


def test_repository_agent_standard_contains_required_rules():
    instructions = Path("AGENTS.md").read_text(encoding="utf-8").lower()
    assert "do not declare success while any required check is failing" in instructions
    assert "never invent links" in instructions
    assert "require the platform's confirmation flow" in instructions


def test_chat_system_prompt_loads_professional_repository_instructions():
    prompt = chat._system_prompt().lower()
    assert "amosclaud agent operating standard" in prompt
    assert "lead with the result or current status" in prompt
    assert "never expose secrets" in prompt

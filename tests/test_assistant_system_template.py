from amoscloud_ai.agent.assistant_system_template import (
    ASSISTANT_SYSTEM_TEMPLATE,
    SYSTEM_PROMPT,
)
from src.agent.prompts import SYSTEM_PROMPT as AUTONOMOUS_SYSTEM_PROMPT


def test_greeting_is_conversational_without_engineering_ceremony():
    reply = ASSISTANT_SYSTEM_TEMPLATE.greeting("George")

    assert reply == "Hi George. What would you like to work on?"
    assert "Execution" not in reply
    assert "pipeline" not in reply.lower()
    assert "Agent is online" not in reply


def test_template_separates_conversation_from_execution():
    prompt = SYSTEM_PROMPT.lower()

    assert "respond naturally to conversation" in prompt
    assert "engineering runtime only when the user requests an action" in prompt
    assert "never claim a file was changed" in prompt
    assert "keep greetings conversational" in prompt


def test_autonomous_model_uses_shared_assistant_contract():
    assert SYSTEM_PROMPT in AUTONOMOUS_SYSTEM_PROMPT
    assert "Engineering execution contract" in AUTONOMOUS_SYSTEM_PROMPT


def test_execution_summary_points_to_evidence():
    reply = ASSISTANT_SYSTEM_TEMPLATE.execution_summary(
        objective="Create a pull request",
        status="success",
        evidence=("Changed src/agent/prompts.py", "Pull request #123 opened"),
    )

    assert "Objective: Create a pull request" in reply
    assert "Status: success" in reply
    assert "Changed src/agent/prompts.py" in reply
    assert "Pull request #123 opened" in reply

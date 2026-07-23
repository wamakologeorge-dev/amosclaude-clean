from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_autonomous_codex_components_exist_for_bot_integration() -> None:
    expected = [
        "amoscloud_ai/autonomous_codex_config.py",
        "amoscloud_ai/codex_system_bundle.py",
        "amoscloud_ai/autonomous_api_chain.py",
        "amoscloud_ai/agent/models/codex_provider.py",
        "amoscloud_ai/agent/runtime.py",
        "amoscloud_ai/agent/bootstrap.py",
        "amoscloud_ai/agent/preflight.py",
        "amosclaud_bot/autonomous_planning.py",
        "amosclaud_bot/dispatcher.py",
    ]
    for path in expected:
        assert (ROOT / path).exists(), path

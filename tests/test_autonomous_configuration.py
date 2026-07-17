from pathlib import Path

from amoscloud_ai.agent.autonomous_keys import AutonomousKeyStore
from amoscloud_ai.agent.preflight import run_preflight


def test_autonomous_key_is_generated_and_verified(tmp_path):
    store = AutonomousKeyStore(tmp_path / "keys" / "autonomous.json")

    generated = store.generate()

    assert generated.secret.startswith(f"ak_{generated.key_id}_")
    assert store.verify(generated.secret) is True
    assert store.verify("ak_wrong") is False
    persisted = store.path.read_text(encoding="utf-8")
    assert generated.secret not in persisted


def test_preflight_reports_ready_with_valid_local_configuration(tmp_path, monkeypatch):
    config = tmp_path / "autonomous.toml"
    config.write_text(
        """
[agent]
name = "test"
[model]
provider = "openai"
[workspace]
default_root = "workspace"
[permissions]
auto_approve_read = true
""".strip(),
        encoding="utf-8",
    )
    workspace = tmp_path / "workspace"
    key_store_path = tmp_path / "keys" / "autonomous.json"
    AutonomousKeyStore(key_store_path).generate()

    monkeypatch.setenv("AMOSCLAUD_CODEX_CONFIG", str(config))
    monkeypatch.setenv("AMOSCLAUD_WORKSPACE", str(workspace))
    monkeypatch.setenv("AMOSCLAUD_AGENT_KEY_STORE", str(key_store_path))
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("AMOSCLAUD_CODEX_MODEL", "test-model")

    report = run_preflight()

    assert report.ready is True
    assert all(report.checks.values())
    assert report.errors == []


def test_preflight_never_exposes_openai_key(tmp_path, monkeypatch):
    config = tmp_path / "autonomous.toml"
    config.write_text(
        "[agent]\nname='test'\n[model]\nprovider='openai'\n[workspace]\nroot='.'\n[permissions]\nauto_approve_read=true\n",
        encoding="utf-8",
    )
    workspace = tmp_path / "workspace"
    key_store_path = tmp_path / "keys" / "autonomous.json"
    AutonomousKeyStore(key_store_path).generate()
    secret = "sensitive-upstream-key"

    monkeypatch.setenv("AMOSCLAUD_CODEX_CONFIG", str(config))
    monkeypatch.setenv("AMOSCLAUD_WORKSPACE", str(workspace))
    monkeypatch.setenv("AMOSCLAUD_AGENT_KEY_STORE", str(key_store_path))
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    monkeypatch.setenv("AMOSCLAUD_CODEX_MODEL", "test-model")

    report_text = str(run_preflight().as_dict())

    assert secret not in report_text

from pathlib import Path

from amoscloud_ai.api.routes import chat


def test_agent_operating_standard_is_loaded_into_provider_prompt(monkeypatch, tmp_path):
    standard = tmp_path / "AGENTS.md"
    standard.write_text(
        "Use clear, respectful, businesslike language.\n"
        "Never claim tests passed unless a first-party action confirmed it.\n"
        "Distinguish completed work from work in progress.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(chat, "_repository_root", lambda: Path(tmp_path))

    prompt = chat._system_prompt()

    assert "clear, respectful, businesslike language" in prompt
    assert "Never claim tests passed" in prompt
    assert "completed work from work in progress" in prompt


def test_repository_action_confirmation_is_specific_and_evidence_based():
    source = Path(chat.__file__).read_text(encoding="utf-8")

    assert 'Repository "{repository.name}" was created successfully in Amosclaud.' in source
    assert 'provider="amosclaud-repository-action"' in source
    assert 'task_status="completed"' in source
    assert 'task_url=f"/workspace/{repository.id}"' in source


def test_professional_standard_prohibits_unsupported_operational_claims():
    standard = (Path(chat.__file__).resolve().parents[3] / "AGENTS.md").read_text(encoding="utf-8")

    assert "Never claim that code was changed" in standard
    assert "first-party action confirmed it" in standard
    assert "Never invent logs" in standard
    assert "Do not silently substitute a simulation" in standard
    assert "Treat destructive actions as high risk" in standard

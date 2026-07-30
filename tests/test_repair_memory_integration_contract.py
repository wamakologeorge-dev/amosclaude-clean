"""Repository contracts for Amosclaud Storage repair memory integration."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_repair_candidate_recalls_memory_without_executing_old_patches() -> None:
    source = (ROOT / ".github" / "scripts" / "amosclaud_repair_candidate.py").read_text(
        encoding="utf-8"
    )

    assert 'memory_context(evidence + "\\n" + feedback)' in source
    assert "Do not copy old patches" not in source
    assert "declarative hints, not executable code" in source
    assert '"memory_consulted": True' in source
    assert "git apply" in source


def test_daily_agent_reads_level_and_has_repository_ollama_fallback() -> None:
    workflow = (ROOT / ".github" / "workflows" / "daily-build.yml").read_text(encoding="utf-8")
    gateway = (ROOT / "amosclaud_cron_gateway.py").read_text(encoding="utf-8")

    assert "ref: amosclaud-memory" in workflow
    assert "Report earned capability level" in workflow
    assert "OLLAMA_API_KEY: ${{ secrets.OLLAMA_API_KEY }}" in workflow
    assert "AMOSCLAUD_MODEL_TOKEN: ${{ secrets.OLLAMA_API_KEY }}" in workflow
    assert "_provider_fallback" in gateway
    assert "provider.reply" in gateway


def test_only_successful_repair_control_runs_can_teach_memory() -> None:
    workflow = (ROOT / ".github" / "workflows" / "amosclaud-repair-memory-learn.yml").read_text(
        encoding="utf-8"
    )

    assert "github.event.workflow_run.conclusion == 'success'" in workflow
    assert "amosclaud-repair-control-${{ env.SOURCE_RUN_ID }}" in workflow
    assert "--verification-report" in workflow
    assert "git -C memory-store push origin HEAD:amosclaud-memory" in workflow


def test_doctor_and_fixer_use_shared_verified_memory() -> None:
    source = (ROOT / "amoscloud_ai" / "repair_engine" / "__init__.py").read_text(encoding="utf-8")

    assert "VerifiedRepairMemory.for_repository" in source
    assert "No old patch was executed" in source
    assert "AutonomousDecisionEngine.decide = _memory_guided_decide" in source
    assert "AutonomousRepairEngine.run = _memory_aware_autonomous_run" in source

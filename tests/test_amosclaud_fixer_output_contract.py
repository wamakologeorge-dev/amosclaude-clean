"""Contracts for durable Amosclaud fixer evidence and truthful step status."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "amosclaud-fixer.yml"


def _workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_fixer_writes_live_output_outside_the_cleaned_repository() -> None:
    workflow = _workflow_text()

    assert 'output_file="$RUNNER_TEMP/amosclaud-fixer-output.txt"' in workflow
    assert 'tee "$output_file"' in workflow
    assert 'cp "$output_file" amosclaud-fixer-output.txt' in workflow
    assert "tee amosclaud-fixer-output.txt" not in workflow


def test_fixer_preserves_the_python_exit_code_after_tee() -> None:
    workflow = _workflow_text()

    assert 'fixer_status="${PIPESTATUS[0]}"' in workflow
    assert 'exit "$fixer_status"' in workflow


def test_fixer_always_emits_a_boolean_verified_output() -> None:
    workflow = _workflow_text()

    assert 'verified="$(grep -m1' in workflow
    assert 'verified=false' in workflow
    assert 'echo "AMOSCLAUD_FIX_VERIFIED=$verified" >> "$GITHUB_OUTPUT"' in workflow


def test_failure_evidence_is_copied_before_the_step_exits() -> None:
    workflow = _workflow_text()

    copy_position = workflow.index('cp "$output_file" amosclaud-fixer-output.txt')
    exit_position = workflow.index('exit "$fixer_status"')
    assert copy_position < exit_position

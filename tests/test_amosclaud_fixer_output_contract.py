"""Contracts for the unified Amosclaud repair evidence and compatibility entrypoint."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHIM = ROOT / ".github" / "workflows" / "amosclaud-fixer.yml"
CONTROL = ROOT / ".github" / "workflows" / "amosclaud-repair-control-plane.yml"


def test_legacy_fixer_is_manual_only_and_delegates_to_control_plane() -> None:
    source = SHIM.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in source
    assert "workflow_run:" not in source
    assert "status:" not in source
    assert "schedule:" not in source
    assert "gh workflow run amosclaud-repair-control-plane.yml" in source


def test_control_plane_preserves_live_and_structured_evidence() -> None:
    source = CONTROL.read_text(encoding="utf-8")
    assert "Collect exact failed-check evidence" in source
    assert "amosclaud-repair-failure.log" in source
    assert "amosclaud-candidate-report.json" in source
    assert "amosclaud-verification-report.json" in source
    assert "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a" in source


def test_candidate_and_verifier_statuses_are_truthful() -> None:
    source = CONTROL.read_text(encoding="utf-8")
    assert "status=${PIPESTATUS[0]}" in source
    assert 'echo "applied=true"' in source
    assert 'echo "applied=false"' in source
    assert 'echo "verified=$([ "$status" -eq 0 ] && echo true || echo false)"' in source
    assert "The repair candidate failed the credential-free adaptive pre-run and was discarded." in source

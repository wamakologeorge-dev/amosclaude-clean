"""Tests for the earned agent level.

The point of these tests is adversarial: they try to inflate the level the ways
an agent under pressure would, and insist the ledger refuses.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from amosclaud_ci.earned_level import Attestation, LevelLedger, declared_level, level_report


def attest(capability: str, oracle: str) -> Attestation:
    return Attestation(
        capability=capability,
        claim=f"{capability} works",
        oracle=oracle,
        evidence="see report",
    )


def test_a_capability_with_a_passing_oracle_counts(tmp_path):
    ledger = LevelLedger(tmp_path / "ledger.jsonl")
    ledger.record(attest("reads-files", "test -f " + str(tmp_path / "ledger.jsonl")))
    assert ledger.earned_level() == 1


def test_a_capability_whose_oracle_fails_does_not_count(tmp_path):
    ledger = LevelLedger(tmp_path / "ledger.jsonl")
    ledger.record(attest("imaginary", "test -f /definitely/not/here"))
    assert ledger.earned_level() == 0


@pytest.mark.parametrize("oracle", ["true", ":", "echo done", "exit 0", "python -c pass"])
def test_an_oracle_that_cannot_fail_never_counts(tmp_path, oracle):
    """The cheapest cheat: attach a check that always passes."""
    ledger = LevelLedger(tmp_path / "ledger.jsonl")
    ledger.record(attest("pretend", oracle))
    assert ledger.earned_level() == 0
    detail = ledger.verify()[0].detail
    assert "cannot fail" in detail


def test_an_attestation_with_no_oracle_never_counts(tmp_path):
    ledger = LevelLedger(tmp_path / "ledger.jsonl")
    ledger.record(attest("trust-me", ""))
    assert ledger.earned_level() == 0


def test_the_stored_verdict_is_never_trusted(tmp_path):
    """A level that was true yesterday is not evidence today."""
    marker = tmp_path / "capability-present"
    marker.write_text("yes", encoding="utf-8")
    ledger = LevelLedger(tmp_path / "ledger.jsonl")
    ledger.record(attest("depends-on-marker", f"test -f {marker}"))
    assert ledger.earned_level() == 1

    marker.unlink()  # the capability regresses
    assert ledger.earned_level() == 0, "the ledger must re-check, not remember"


def test_repeating_a_claim_does_not_stack_up_levels(tmp_path):
    ledger = LevelLedger(tmp_path / "ledger.jsonl")
    for _ in range(25):
        ledger.record(attest("one-thing", "test -d " + str(tmp_path)))
    assert ledger.earned_level() == 1, "the same capability claimed twice is still one capability"


def test_declared_level_above_earned_is_reported_as_an_unearned_gap(tmp_path, monkeypatch):
    monkeypatch.setenv("AMOSCLAUD_AUTONOMOUS_LEVEL", "3200")
    ledger = LevelLedger(tmp_path / "ledger.jsonl")
    ledger.record(attest("one-real-thing", "test -d " + str(tmp_path)))

    report = level_report(ledger)
    assert declared_level() == 3200
    assert report["earned_level"] == 1
    assert report["unearned_gap"] == 3199
    assert report["honest"] is False


def test_a_level_backed_by_evidence_reports_as_honest(tmp_path, monkeypatch):
    monkeypatch.setenv("AMOSCLAUD_AUTONOMOUS_LEVEL", "1")
    ledger = LevelLedger(tmp_path / "ledger.jsonl")
    ledger.record(attest("real", "test -d " + str(tmp_path)))
    report = level_report(ledger)
    assert report["honest"] is True
    assert report["unearned_gap"] == 0


def test_corrupt_ledger_lines_are_ignored_rather_than_counted(tmp_path):
    path = Path(tmp_path / "ledger.jsonl")
    path.write_text("not json at all\n{}\n", encoding="utf-8")
    ledger = LevelLedger(path)
    assert ledger.attestations() == []
    assert ledger.earned_level() == 0

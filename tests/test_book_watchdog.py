from __future__ import annotations

import json
from pathlib import Path

import pytest

from amoscloud_ai.book_watchdog import (
    BookWatchdogError,
    RepositoryBookWatchdog,
    detect_secrets,
    redact_book_text,
    secret_verdict,
)


def test_high_confidence_openai_style_literal_blocks_without_echoing_value() -> None:
    candidate = "sk-" + "aB7_9xQ2mN4pR6tV8yZ1cD3fG5hJ7kL9"
    text = f'OPENAI_API_KEY = "{candidate}"'

    verdict = secret_verdict(text)

    assert verdict["allowed"] is False
    assert verdict["blocking_count"] >= 1
    assert any(
        item["classification"] in {"confirmed_secret", "probable_secret"}
        for item in verdict["findings"]
    )
    assert candidate not in json.dumps(verdict)


def test_environment_and_secret_manager_references_are_not_leaks() -> None:
    samples = [
        'OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]',
        "const key = process.env.OPENAI_API_KEY;",
        "OPENAI_API_KEY=${OPENAI_API_KEY}",
        "OPENAI_API_KEY={{ secrets.OPENAI_API_KEY }}",
        "OPENAI_API_KEY=<yourkey>",
        "OPENAI_API_KEY=example-value-not-a-real-key",
    ]

    for sample in samples:
        verdict = secret_verdict(sample)
        assert verdict["allowed"] is True, sample
        assert verdict["blocking_count"] == 0, sample


def test_hash_uuid_and_normal_random_identifiers_do_not_trigger_block() -> None:
    text = "\n".join(
        [
            'CHECKSUM = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"',
            'REQUEST_ID = "550e8400-e29b-41d4-a716-446655440000"',
            'BUILD_ID = "01J8Z8H6X4JQ3C7V5N2W1T9M0P"',
        ]
    )

    verdict = secret_verdict(text)

    assert verdict["allowed"] is True
    assert verdict["blocking_count"] == 0


def test_suspicious_classification_warns_without_blocking() -> None:
    # An access identifier can deserve review without proving that a secret was leaked.
    verdict = secret_verdict("AWS_ACCESS_KEY_ID=AKIAABCDEFGHIJKLMNOP")

    assert verdict["allowed"] is True
    assert verdict["blocking_count"] == 0
    assert verdict["warning_count"] >= 1
    assert any(item["classification"] == "suspicious" for item in verdict["findings"])


def test_private_key_material_is_confirmed_and_redacted() -> None:
    source = "-----BEGIN PRIVATE KEY-----\nnot-a-real-private-key-body\n-----END PRIVATE KEY-----"

    findings = detect_secrets(source)
    redacted, count = redact_book_text(source)

    assert findings
    assert findings[0].classification == "confirmed_secret"
    assert count >= 1
    assert "BEGIN PRIVATE KEY" not in redacted


def test_slapface_blocks_future_work_until_matching_handoff_is_resolved(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    watchdog = RepositoryBookWatchdog(repository)

    handoff = watchdog.block_handoff(
        actor="agent-one",
        summary="The previous build stopped before verification finished.",
        chapter_link=".Amosclaud/book/chapters/07-actions-ci.md#verification",
        missing_pieces=["Run the focused verification and record the result."],
    )

    blocked = watchdog.preflight(actor="agent-two", action="inspect")
    assert blocked["work_allowed"] is False
    assert blocked["reason"] == "unfinished_handoff"
    assert blocked["handoff"]["handoff_id"] == handoff["handoff_id"]

    with pytest.raises(BookWatchdogError, match="does not match"):
        watchdog.resolve_handoff(
            actor="agent-two",
            handoff_id="wrong-id",
            evidence=["Focused verification passed."],
        )

    watchdog.resolve_handoff(
        actor="agent-two",
        handoff_id=handoff["handoff_id"],
        evidence=["Focused verification passed with no blocking checks."],
    )
    released = watchdog.preflight(actor="agent-two", action="inspect")
    assert released["work_allowed"] is True


def test_secret_block_creates_slapface_without_storing_candidate(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    watchdog = RepositoryBookWatchdog(repository)
    candidate = "sk-" + "K7mP9qR2sT4vW6xY8zA1bC3dE5fG7hJ9"

    verdict = watchdog.preflight(
        actor="developer",
        action="write-file",
        proposed_text=f'OPENAI_API_KEY="{candidate}"',
    )

    assert verdict["work_allowed"] is False
    assert verdict["reason"] == "probable_secret_exposure"
    runtime = repository / ".Amosclaud" / "book" / ".runtime"
    stored = "\n".join(
        path.read_text(encoding="utf-8")
        for path in runtime.rglob("*")
        if path.is_file()
    )
    assert candidate not in stored
    assert "credential exposure" in stored

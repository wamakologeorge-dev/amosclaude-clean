from __future__ import annotations

from amoscloud_ai.health_contract import evaluate_health, render_markdown


def check(name: str, conclusion: str | None, status: str = "completed") -> dict[str, object]:
    return {"name": name, "status": status, "conclusion": conclusion}


def test_verified_requires_every_required_check_and_declared_skips() -> None:
    result = evaluate_health(
        [
            check("Fast PR Gate", "success"),
            check("Build and Verify", "success"),
            check("Amosclaud Fork PR Fixer", "skipped"),
        ],
        required=("Fast PR Gate", "Build and Verify", "Amosclaud Fork PR Fixer"),
        expected_skips=("*Fork PR Fixer",),
    )

    assert result["overall"] == "VERIFIED"
    assert result["percentage"] == 100
    assert result["truthful_100_percent"] is True
    assert result["exit_code"] == 0


def test_unexpected_skip_prevents_a_100_percent_claim() -> None:
    result = evaluate_health(
        [check("Fast PR Gate", "success"), check("Build and Verify", "skipped")],
        required=("Fast PR Gate", "Build and Verify"),
    )

    assert result["overall"] == "ACTION_NEEDED"
    assert result["percentage"] == 50
    assert result["truthful_100_percent"] is False
    assert result["counts"]["UNEXPECTED_SKIP"] == 1


def test_missing_and_pending_checks_remain_visible() -> None:
    missing = evaluate_health(
        [check("Fast PR Gate", "success")],
        required=("Fast PR Gate", "Build and Verify"),
    )
    assert missing["overall"] == "ACTION_NEEDED"
    assert missing["counts"]["MISSING"] == 1

    pending = evaluate_health(
        [
            check("Fast PR Gate", "success"),
            check("Build and Verify", None, status="in_progress"),
        ],
        required=("Fast PR Gate", "Build and Verify"),
    )
    assert pending["overall"] == "PENDING"
    assert pending["truthful_100_percent"] is False


def test_observed_failure_blocks_verified_health_even_when_not_required() -> None:
    result = evaluate_health(
        [
            check("Fast PR Gate", "success"),
            check("Security Scan", "failure"),
        ],
        required=("Fast PR Gate",),
        optional=("Security Scan",),
    )

    assert result["percentage"] == 100
    assert result["overall"] == "ACTION_NEEDED"
    assert result["truthful_100_percent"] is False


def test_markdown_distinguishes_expected_skip_from_failure() -> None:
    result = evaluate_health(
        [
            check("Fast PR Gate", "success"),
            check("Amosclaud Model Agent", "skipped"),
        ],
        required=("Fast PR Gate", "Amosclaud Model Agent"),
        expected_skips=("Amosclaud Model Agent",),
    )

    report = render_markdown(result)
    assert "VERIFIED" in report
    assert "EXPECTED_SKIP" in report
    assert "ACTION_NEEDED" not in report

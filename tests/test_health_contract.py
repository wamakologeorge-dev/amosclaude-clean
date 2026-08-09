from __future__ import annotations

from amoscloud_ai.health_contract import evaluate_health, render_markdown


def check(
    name: str,
    conclusion: str | None,
    status: str = "completed",
    **extra: object,
) -> dict[str, object]:
    return {"name": name, "status": status, "conclusion": conclusion, **extra}


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
    assert result["observed_total"] == 3
    assert result["observed_verified"] == 3
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


def test_per_check_event_contract_can_allow_a_conditional_skip() -> None:
    result = evaluate_health(
        [
            check("Fast PR Gate", "success"),
            check(
                "cmood trigger [run 7]",
                "skipped",
                display_name="cmood Autonomous Agent Trigger",
                event="issue_comment",
                skip_expected=True,
            ),
        ],
        required=("Fast PR Gate", "cmood trigger [run 7]"),
    )

    assert result["overall"] == "VERIFIED"
    assert result["percentage"] == 100
    assert result["checks"][1]["state"] == "EXPECTED_SKIP"
    assert "event=issue_comment" in result["checks"][1]["detail"]


def test_missing_and_pending_checks_remain_visible() -> None:
    missing = evaluate_health(
        [check("Fast PR Gate", "success")],
        required=("Fast PR Gate", "Build and Verify"),
    )
    assert missing["overall"] == "ACTION_NEEDED"
    assert missing["percentage"] == 50
    assert missing["counts"]["MISSING"] == 1

    pending = evaluate_health(
        [
            check("Fast PR Gate", "success"),
            check("Build and Verify", None, status="in_progress"),
        ],
        required=("Fast PR Gate", "Build and Verify"),
    )
    assert pending["overall"] == "PENDING"
    assert pending["percentage"] == 50
    assert pending["truthful_100_percent"] is False


def test_observed_failure_blocks_verified_health_and_reduces_percentage() -> None:
    result = evaluate_health(
        [
            check("Fast PR Gate", "success"),
            check("Security Scan", "failure"),
        ],
        required=("Fast PR Gate",),
        optional=("Security Scan",),
    )

    assert result["percentage"] == 50
    assert result["overall"] == "ACTION_NEEDED"
    assert result["observed_total"] == 2
    assert result["observed_verified"] == 1
    assert result["truthful_100_percent"] is False


def test_observed_pending_check_never_displays_100_percent() -> None:
    result = evaluate_health(
        [
            check("Fast PR Gate", "success"),
            check("Security Scan", None, status="queued"),
        ],
        required=("Fast PR Gate",),
        optional=("Security Scan",),
    )

    assert result["overall"] == "PENDING"
    assert result["percentage"] == 50
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
    assert "Observed verification: 100%" in report
    assert "EXPECTED_SKIP" in report
    assert "ACTION_NEEDED" not in report

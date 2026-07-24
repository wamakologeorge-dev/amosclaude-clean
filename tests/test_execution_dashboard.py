from amosclaud_bot.execution_dashboard import (
    DASHBOARD_MARKER,
    TestCard,
    _latest_dashboard_comment,
    render_dashboard,
)


def test_live_dashboard_renders_real_test_cards_and_progress() -> None:
    body = render_dashboard(
        objective="fix the parser regression",
        current_stage="verify",
        outcome="running",
        files=["amosclaud_bot/bot.py", "tests/test_amosclaud_bot.py"],
        tests=[
            TestCard("Python compilation", "passed", "compileall completed"),
            TestCard("Targeted pytest", "passed", "42 passed"),
            TestCard("Final verification", "running", "workflow still active"),
        ],
        branch="amosclaud-bot/fix-42",
    )

    assert DASHBOARD_MARKER in body
    assert "👁️ Amosclaud Live Execution" in body
    assert "Test cards" in body
    assert "Python compilation" in body
    assert "42 passed" in body
    assert "amosclaud_bot/bot.py" in body
    assert "never reports PASS" in body


def test_failed_stage_is_never_presented_as_passed() -> None:
    body = render_dashboard(
        objective="repair CI",
        current_stage="test",
        outcome="failed",
        tests=[TestCard("Targeted pytest", "failed", "1 failed")],
    )

    assert "**Test suite** — FAILED" in body
    assert "`FAILED`" in body
    assert "1 failed" in body
    assert "Commit & pull request** — PENDING" in body


def test_completed_dashboard_shows_delivery_evidence() -> None:
    body = render_dashboard(
        objective="add dashboard",
        current_stage="publish",
        outcome="passed",
        tests=[TestCard("Dashboard tests", "passed", "3 passed")],
        commit="abc1234",
        pull_request="#491",
        branch="feature/live-execution-dashboard",
    )

    assert "`100%`" in body
    assert "`abc1234`" in body
    assert "#491" in body
    assert "Commit & pull request** — PASSED" in body


def test_latest_dashboard_comment_is_reused() -> None:
    comments = [
        {"id": 1, "body": "ordinary comment"},
        {"id": 2, "body": f"{DASHBOARD_MARKER}\nold"},
        {"id": 3, "body": f"{DASHBOARD_MARKER}\nnew"},
    ]
    assert _latest_dashboard_comment(comments) == 3
    assert _latest_dashboard_comment([{"id": 1, "body": "none"}]) is None

from amosclaud_bot.comment_style import MAX_PUBLIC_COMMENT, compact_public_comment


def test_short_comment_is_preserved() -> None:
    message = "### Amosclaud — Fix complete\nStatus: PASS"
    assert compact_public_comment(message) == message


def test_long_comment_keeps_decisive_lines_and_hides_bulk() -> None:
    message = "\n".join(
        [
            "### Amosclaud Bot — Professional PR Review",
            "**Autonomous status:** **COMPLETED**",
            "**Risk:** **HIGH**",
            "## Summary",
            "A" * 900,
            "**Files changed:** 8",
            "## Recommendation",
            "**CHANGES REQUESTED**",
        ]
    )
    compact = compact_public_comment(message)

    assert len(compact) <= MAX_PUBLIC_COMMENT
    assert "Professional PR Review" in compact
    assert "**Risk:** **HIGH**" in compact
    assert "**Files changed:** 8" in compact
    assert "**CHANGES REQUESTED**" in compact
    assert "A" * 100 not in compact
    assert "Details: see GitHub Actions / PR checks." in compact


def test_long_inspection_keeps_status_and_priority() -> None:
    message = "\n".join(
        [
            "### Amosclaud Autonomous Assistant — Inspect",
            "**Status:** **COMPLETED**",
            "Repository findings",
            "B" * 900,
            "- **HIGH:** CI/CD",
            "- **MEDIUM:** Security",
            "- **LOW:** Tests",
        ]
    )
    compact = compact_public_comment(message)

    assert "**Status:** **COMPLETED**" in compact
    assert "**HIGH:** CI/CD" in compact
    assert "**MEDIUM:** Security" in compact
    assert "**LOW:** Tests" in compact


def test_workflow_status_board_is_preserved() -> None:
    message = "### Amosclaud — Workflow Status\n\n" + "\n".join(
        f"🟩 **Workflow {index}** — PASSED" for index in range(12)
    )
    compact = compact_public_comment(message)

    assert compact.startswith("### Amosclaud — Workflow Status")
    assert "Workflow 0" in compact
    assert "Workflow 11" in compact


def test_verified_result_markers_survive_long_comment() -> None:
    message = "\n".join(
        [
            "### Amosclaud — Verified result",
            "🟩 **Result:** PASSED",
            "🟩 **Compilation:** PASSED",
            "🟩 **Tests:** PASSED",
            "**Files changed:** 2",
            "C" * 900,
        ]
    )
    compact = compact_public_comment(message)

    assert "**Result:** PASSED" in compact
    assert "**Compilation:** PASSED" in compact
    assert "**Tests:** PASSED" in compact
    assert "**Files changed:** 2" in compact

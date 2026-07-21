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

from pathlib import Path

from amoscloud_ai.autonomous_server import _conflict_marker_check


def test_markdown_equals_heading_is_not_a_merge_conflict(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("Results\n=======\n", encoding="utf-8")

    result = _conflict_marker_check(tmp_path)

    assert result.status == "passed"


def test_complete_merge_conflict_block_is_detected(tmp_path: Path) -> None:
    (tmp_path / "broken.py").write_text(
        "<<<<<<< HEAD\nleft = 1\n=======\nright = 2\n>>>>>>> branch\n",
        encoding="utf-8",
    )

    result = _conflict_marker_check(tmp_path)

    assert result.status == "failed"
    assert "broken.py" in result.details[0]

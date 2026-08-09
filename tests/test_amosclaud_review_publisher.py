from __future__ import annotations

from typing import Any

from amosclaud_bot.review_publisher import publish_review


class FakeBot:
    repository = "owner/repo"

    def __init__(self, *, change_head: bool = False) -> None:
        self.change_head = change_head
        self.pr_reads = 0
        self.calls: list[tuple[str, str, dict[str, Any] | None]] = []
        self.comments: list[tuple[int, str]] = []

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        self.calls.append((method, path, payload))
        if method == "GET" and path == "/repos/owner/repo/pulls/7":
            self.pr_reads += 1
            sha = (
                "newsha987654321" if self.change_head and self.pr_reads > 1 else "headsha123456789"
            )
            return {
                "title": "Add review capability",
                "base": {"ref": "main"},
                "head": {"ref": "feature/review", "sha": sha},
            }
        if method == "GET" and "pulls/7/files" in path and "&page=1" in path:
            return [
                {
                    "filename": f"src/file_{index}.py",
                    "additions": 1,
                    "deletions": 0,
                }
                for index in range(100)
            ]
        if method == "GET" and "pulls/7/files" in path and "&page=2" in path:
            return [
                {
                    "filename": "tests/test_review.py",
                    "additions": 4,
                    "deletions": 1,
                }
            ]
        if method == "GET" and "check-runs" in path and "&page=1" in path:
            return {
                "check_runs": [
                    {
                        "name": "Fast PR Gate",
                        "status": "completed",
                        "conclusion": "success",
                    },
                    {
                        "name": "Security Scan",
                        "status": "in_progress",
                        "conclusion": None,
                    },
                ]
            }
        if method == "POST" and path == "/repos/owner/repo/pulls/7/reviews":
            return {"id": 123}
        raise AssertionError((method, path, payload))

    def post_comment(self, issue_number: int, body: str) -> None:
        self.comments.append((issue_number, body))


def review_payload() -> dict[str, Any]:
    return {
        "comment": {
            "body": "@amosclaud review this PR for security and test risk",
            "author_association": "OWNER",
        },
        "issue": {
            "number": 7,
            "pull_request": {"url": "https://api.github.com/repos/owner/repo/pulls/7"},
        },
    }


def test_formal_review_is_bound_to_exact_head_and_non_blocking() -> None:
    bot = FakeBot()

    result = publish_review(bot, review_payload())

    assert result.submitted is True
    assert result.status == "SUBMITTED"
    assert result.commit_sha == "headsha123456789"
    review_calls = [call for call in bot.calls if call[1].endswith("/reviews")]
    assert len(review_calls) == 1
    _, _, payload = review_calls[0]
    assert payload is not None
    assert payload["event"] == "COMMENT"
    assert payload["commit_id"] == "headsha123456789"
    assert "automated, read-only, non-blocking" in payload["body"]
    assert "Files changed:** 101" in payload["body"]
    assert "Security Scan (in_progress)" in payload["body"]
    assert bot.comments == []


def test_head_change_defers_review_instead_of_publishing_stale_result() -> None:
    bot = FakeBot(change_head=True)

    result = publish_review(bot, review_payload())

    assert result.submitted is False
    assert result.status == "HEAD_CHANGED"
    assert not any(call[1].endswith("/reviews") for call in bot.calls)
    assert len(bot.comments) == 1
    assert "No stale formal review was submitted" in bot.comments[0][1]


def test_non_review_comment_is_ignored() -> None:
    bot = FakeBot()
    payload = review_payload()
    payload["comment"]["body"] = "@amosclaud status"

    result = publish_review(bot, payload)

    assert result.applicable is False
    assert result.status == "NOT_APPLICABLE"
    assert bot.calls == []
    assert bot.comments == []

from __future__ import annotations

from typing import Any

from amosclaud_bot.review_publisher import publish_review


class FakeBot:
    repository = "owner/repo"

    def __init__(
        self,
        *,
        change_head: bool = False,
        checks: list[dict[str, object]] | None = None,
    ) -> None:
        self.change_head = change_head
        self.checks = checks or [
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
            return {"check_runs": self.checks}
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


def submitted_body(bot: FakeBot) -> str:
    review_calls = [call for call in bot.calls if call[1].endswith("/reviews")]
    assert len(review_calls) == 1
    payload = review_calls[0][2]
    assert payload is not None
    return str(payload["body"])


def test_formal_review_is_bound_to_exact_head_and_non_blocking() -> None:
    bot = FakeBot()

    result = publish_review(bot, review_payload())

    assert result.submitted is True
    assert result.status == "SUBMITTED"
    assert result.commit_sha == "headsha123456789"
    review_calls = [call for call in bot.calls if call[1].endswith("/reviews")]
    _, _, payload = review_calls[0]
    assert payload is not None
    assert payload["event"] == "COMMENT"
    assert payload["commit_id"] == "headsha123456789"
    body = str(payload["body"])
    assert "automated, read-only, non-blocking" in body
    assert "Files changed:** 101" in body
    assert "Security Scan (in_progress)" in body
    assert "METADATA AND CHECK EVIDENCE ONLY" in body
    assert "**CHANGES REQUESTED**" in body
    assert "**APPROVE**" not in body
    assert bot.comments == []


def test_all_green_metadata_review_still_requires_human_content_review() -> None:
    bot = FakeBot(
        checks=[
            {
                "name": "Fast PR Gate",
                "status": "completed",
                "conclusion": "success",
            },
            {
                "name": "CodeQL",
                "status": "completed",
                "conclusion": "success",
            },
        ]
    )

    result = publish_review(bot, review_payload())
    body = submitted_body(bot)

    assert result.submitted is True
    assert "**NEEDS HUMAN REVIEW**" in body
    assert "**APPROVE**" not in body
    assert "Complete patch semantics were not analyzed" in body


def test_failing_security_check_blocks_review_and_raises_risk() -> None:
    bot = FakeBot(
        checks=[
            {
                "name": "CodeQL",
                "status": "completed",
                "conclusion": "failure",
            }
        ]
    )

    publish_review(bot, review_payload())
    body = submitted_body(bot)

    assert "**CHANGES REQUESTED**" in body
    assert "**BLOCKED — CHANGES REQUIRED**" in body
    assert "`CodeQL`" in body
    assert "**Risk:** **HIGH**" in body


def test_failing_nonsecurity_check_never_recommends_approval() -> None:
    bot = FakeBot(
        checks=[
            {
                "name": "Unit Tests",
                "status": "completed",
                "conclusion": "failure",
            }
        ]
    )

    publish_review(bot, review_payload())
    body = submitted_body(bot)

    assert "**CHANGES REQUESTED**" in body
    assert "Unit Tests (failure)" in body
    assert "**APPROVE**" not in body


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

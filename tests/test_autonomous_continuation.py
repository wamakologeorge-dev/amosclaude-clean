from __future__ import annotations

from typing import Any

from amosclaud_bot import continuation_state, parse_command
from amosclaud_bot.autonomous_planning import (
    encode_plan_marker,
    is_continue_request,
    resolve_continuation,
)


class FakeBot:
    repository = "owner/repository"

    def __init__(self, comments: list[dict[str, Any]]) -> None:
        self.comments = comments
        self.requests = 0
        self.posted: list[tuple[int, str]] = []

    def _request(self, method: str, path: str):
        assert method == "GET"
        assert "/issues/7/comments" in path
        self.requests += 1
        return self.comments

    def post_comment(self, issue_number: int, body: str) -> None:
        self.posted.append((issue_number, body))


def _payload() -> dict[str, Any]:
    return {
        "issue": {"number": 7},
        "comment": {"body": "@amosclaud proceed"},
    }


def test_proceed_phrases_resume_the_latest_plan() -> None:
    assert is_continue_request("proceed")
    assert is_continue_request("@amosclaud proceed")
    assert is_continue_request("@amosclaud proceed with the repair")
    assert is_continue_request("@amosclaud-bot go ahead")


def test_unrelated_objectives_are_not_continuations() -> None:
    assert not is_continue_request("@amosclaud inspect the repository")
    assert not is_continue_request("@amosclaud create a new file")


def test_resolved_plan_is_cached_for_later_workflow_steps(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        continuation_state,
        "STATE_PATH",
        tmp_path / "continuation.json",
    )
    objective = "repair the parser and add a regression test"
    bot = FakeBot(
        [
            {
                "body": "plan\n" + encode_plan_marker("fix", objective),
            }
        ]
    )
    payload = _payload()

    assert resolve_continuation(bot, payload) is False
    assert payload["comment"]["body"] == f"@amosclaud fix {objective}"
    assert bot.requests == 1
    assert parse_command("@amosclaud proceed") == ("fix", objective)

    second_payload = _payload()
    assert resolve_continuation(bot, second_payload) is False
    assert second_payload["comment"]["body"] == f"@amosclaud fix {objective}"
    assert bot.requests == 1


def test_missing_plan_is_cached_without_duplicate_comments(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        continuation_state,
        "STATE_PATH",
        tmp_path / "continuation.json",
    )
    bot = FakeBot([])

    assert resolve_continuation(bot, _payload()) is True
    assert bot.requests == 1
    assert len(bot.posted) == 1
    assert parse_command("@amosclaud proceed") == (None, "")

    assert resolve_continuation(bot, _payload()) is True
    assert bot.requests == 1
    assert len(bot.posted) == 1

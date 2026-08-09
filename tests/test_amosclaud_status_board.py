from amosclaud_bot.status_board import build_status_board, is_status_request


class FakeBot:
    repository = "owner/repo"

    def __init__(self) -> None:
        self.calls: list[str] = []

    def _request(self, method: str, path: str):
        self.calls.append(path)
        if path == "/repos/owner/repo":
            return {"default_branch": "main"}
        if path == "/repos/owner/repo/branches/main":
            return {"commit": {"sha": "mainsha1234567890"}}
        if "head_sha=mainsha1234567890" in path and "page=1" in path:
            return {
                "workflow_runs": [
                    {
                        "id": 1,
                        "name": "Amosclaud AI",
                        "event": "pull_request",
                        "status": "completed",
                        "conclusion": "success",
                    },
                    {
                        "id": 2,
                        "name": "Amosclaud Autonomous",
                        "event": "pull_request",
                        "status": "completed",
                        "conclusion": "failure",
                    },
                    {
                        "id": 3,
                        "name": "CodeQL",
                        "event": "pull_request",
                        "status": "in_progress",
                        "conclusion": None,
                    },
                ]
            }
        raise AssertionError(path)


def test_status_aliases_are_explicit() -> None:
    assert is_status_request("@amosclaud status")
    assert is_status_request("@amosclaud-status")
    assert is_status_request("Amosclaud-status")
    assert not is_status_request("@amosclaud inspect repository")


def test_status_board_uses_exact_commit_workflow_results() -> None:
    bot = FakeBot()
    board = build_status_board(bot, {"issue": {"number": 7}})

    assert "🟩 **Amosclaud AI** — PASSED" in board
    assert "🟥 **Amosclaud Autonomous** — FAILED" in board
    assert "🟨 **CodeQL** — PENDING" in board
    assert "**Overall:** 🟥 ACTION NEEDED" in board
    assert "**Observed verification:** 33%" in board
    assert "**Runs evaluated:** 3" in board
    assert "**Target:** `main`" in board
    assert "**Commit:** `mainsha12345`" in board
    assert any("head_sha=mainsha1234567890" in call for call in bot.calls)
    assert not any("branch=main" in call for call in bot.calls)


def test_all_successful_exact_commit_runs_report_verified_100_percent() -> None:
    class PassingBot(FakeBot):
        def _request(self, method: str, path: str):
            if path == "/repos/owner/repo":
                return {"default_branch": "main"}
            if path == "/repos/owner/repo/branches/main":
                return {"commit": {"sha": "passing123456789"}}
            if "head_sha=passing123456789" in path and "page=1" in path:
                return {
                    "workflow_runs": [
                        {
                            "id": 10,
                            "name": "Amosclaud AI",
                            "event": "pull_request",
                            "status": "completed",
                            "conclusion": "success",
                        },
                        {
                            "id": 11,
                            "name": "Amosclaud Autonomous",
                            "event": "pull_request",
                            "status": "completed",
                            "conclusion": "success",
                        },
                    ]
                }
            raise AssertionError(path)

    board = build_status_board(PassingBot(), {"issue": {"number": 8}})
    assert "**Overall:** 🟩 VERIFIED" in board
    assert "**Observed verification:** 100%" in board
    assert "**Runs evaluated:** 2" in board


def test_event_specific_conditional_skip_is_allowed_only_for_its_event() -> None:
    class SkippingBot(FakeBot):
        event = "issue_comment"

        def _request(self, method: str, path: str):
            if path == "/repos/owner/repo":
                return {"default_branch": "main"}
            if path == "/repos/owner/repo/branches/main":
                return {"commit": {"sha": "skipsha123456789"}}
            if "head_sha=skipsha123456789" in path and "page=1" in path:
                return {
                    "workflow_runs": [
                        {
                            "id": 20,
                            "name": "Repository Behavior Automation",
                            "event": "pull_request",
                            "status": "completed",
                            "conclusion": "success",
                        },
                        {
                            "id": 21,
                            "name": "cmood Autonomous Agent Trigger",
                            "event": self.event,
                            "status": "completed",
                            "conclusion": "skipped",
                        },
                    ]
                }
            raise AssertionError(path)

    allowed = build_status_board(SkippingBot(), {"issue": {"number": 9}})
    assert "**cmood Autonomous Agent Trigger** — EXPECTED_SKIP" in allowed
    assert "**Overall:** 🟩 VERIFIED" in allowed
    assert "**Observed verification:** 100%" in allowed

    push_bot = SkippingBot()
    push_bot.event = "push"
    rejected = build_status_board(push_bot, {"issue": {"number": 10}})
    assert "**cmood Autonomous Agent Trigger** — UNEXPECTED_SKIP" in rejected
    assert "**Overall:** 🟥 ACTION NEEDED" in rejected
    assert "**Observed verification:** 50%" in rejected


def test_pull_request_status_uses_exact_head_sha() -> None:
    class PrBot(FakeBot):
        def _request(self, method: str, path: str):
            self.calls.append(path)
            if path == "/repos/owner/repo/pulls/42":
                return {"head": {"ref": "feature/demo", "sha": "abcdef1234567890"}}
            if "head_sha=abcdef1234567890" in path and "page=1" in path:
                return {
                    "workflow_runs": [
                        {
                            "id": 30,
                            "name": "Build and Verify",
                            "event": "pull_request",
                            "status": "completed",
                            "conclusion": "success",
                        }
                    ]
                }
            raise AssertionError(path)

    bot = PrBot()
    board = build_status_board(bot, {"issue": {"number": 42, "pull_request": {"url": "x"}}})
    assert "🟩 **Build and Verify** — PASSED" in board
    assert "**Overall:** 🟩 VERIFIED" in board
    assert "**Target:** `feature/demo`" in board
    assert any("head_sha=abcdef1234567890" in call for call in bot.calls)


def test_unresolved_exact_commit_refuses_branch_history_verification() -> None:
    class UnresolvedBot(FakeBot):
        def _request(self, method: str, path: str):
            self.calls.append(path)
            if path == "/repos/owner/repo":
                return {"default_branch": "main"}
            if path == "/repos/owner/repo/branches/main":
                return {"commit": {}}
            raise AssertionError(path)

    bot = UnresolvedBot()
    board = build_status_board(bot, {"issue": {"number": 11}})

    assert "exact target commit could not be resolved" in board
    assert "**Overall:** ⬜ INCOMPLETE" in board
    assert "**Observed verification:** 0%" in board
    assert "**Commit:** `unresolved`" in board
    assert not any("/actions/runs" in call for call in bot.calls)


def test_repeated_workflow_failure_cannot_be_hidden_by_later_success() -> None:
    class RepeatedBot(FakeBot):
        def _request(self, method: str, path: str):
            if path == "/repos/owner/repo":
                return {"default_branch": "main"}
            if path == "/repos/owner/repo/branches/main":
                return {"commit": {"sha": "repeated123456789"}}
            if "head_sha=repeated123456789" in path and "page=1" in path:
                return {
                    "workflow_runs": [
                        {
                            "id": 41,
                            "name": "Amosclaud Agent Main",
                            "event": "workflow_run",
                            "status": "completed",
                            "conclusion": "success",
                        },
                        {
                            "id": 40,
                            "name": "Amosclaud Agent Main",
                            "event": "workflow_run",
                            "status": "completed",
                            "conclusion": "failure",
                        },
                    ]
                }
            raise AssertionError(path)

    board = build_status_board(RepeatedBot(), {"issue": {"number": 12}})

    assert board.count("**Amosclaud Agent Main**") == 2
    assert "**Amosclaud Agent Main** — PASSED" in board
    assert "**Amosclaud Agent Main** — FAILED" in board
    assert "**Overall:** 🟥 ACTION NEEDED" in board
    assert "**Observed verification:** 50%" in board


def test_pagination_includes_failures_beyond_the_first_hundred_runs() -> None:
    class PaginatedBot(FakeBot):
        def _request(self, method: str, path: str):
            self.calls.append(path)
            if path == "/repos/owner/repo":
                return {"default_branch": "main"}
            if path == "/repos/owner/repo/branches/main":
                return {"commit": {"sha": "paged1234567890"}}
            if "head_sha=paged1234567890" in path and "page=1" in path:
                return {
                    "workflow_runs": [
                        {
                            "id": 1000 + index,
                            "name": f"Passing workflow {index}",
                            "event": "pull_request",
                            "status": "completed",
                            "conclusion": "success",
                        }
                        for index in range(100)
                    ]
                }
            if "head_sha=paged1234567890" in path and "page=2" in path:
                return {
                    "workflow_runs": [
                        {
                            "id": 2001,
                            "name": "Late failing workflow",
                            "event": "pull_request",
                            "status": "completed",
                            "conclusion": "failure",
                        }
                    ]
                }
            raise AssertionError(path)

    bot = PaginatedBot()
    board = build_status_board(bot, {"issue": {"number": 13}})

    assert "**Overall:** 🟥 ACTION NEEDED" in board
    assert "**Runs evaluated:** 101" in board
    assert "77 additional exact-commit run(s)" in board
    assert any("page=2" in call for call in bot.calls)

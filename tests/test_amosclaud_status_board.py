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
        if "head_sha=mainsha1234567890" in path:
            return {
                "workflow_runs": [
                    {"name": "Amosclaud AI", "status": "completed", "conclusion": "success"},
                    {
                        "name": "Amosclaud Autonomous",
                        "status": "completed",
                        "conclusion": "failure",
                    },
                    {"name": "CodeQL", "status": "in_progress", "conclusion": None},
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
            if "head_sha=passing123456789" in path:
                return {
                    "workflow_runs": [
                        {
                            "name": "Amosclaud AI",
                            "status": "completed",
                            "conclusion": "success",
                        },
                        {
                            "name": "Amosclaud Autonomous",
                            "status": "completed",
                            "conclusion": "success",
                        },
                    ]
                }
            raise AssertionError(path)

    board = build_status_board(PassingBot(), {"issue": {"number": 8}})
    assert "**Overall:** 🟩 VERIFIED" in board
    assert "**Observed verification:** 100%" in board


def test_declared_conditional_skip_is_not_reported_as_failure() -> None:
    class SkippingBot(FakeBot):
        def _request(self, method: str, path: str):
            if path == "/repos/owner/repo":
                return {"default_branch": "main"}
            if path == "/repos/owner/repo/branches/main":
                return {"commit": {"sha": "skipsha123456789"}}
            if "head_sha=skipsha123456789" in path:
                return {
                    "workflow_runs": [
                        {
                            "name": "Repository Behavior Automation",
                            "status": "completed",
                            "conclusion": "success",
                        },
                        {
                            "name": "Amosclaud Model Agent",
                            "status": "completed",
                            "conclusion": "skipped",
                        },
                    ]
                }
            raise AssertionError(path)

    board = build_status_board(SkippingBot(), {"issue": {"number": 9}})
    assert "**Amosclaud Model Agent** — EXPECTED_SKIP" in board
    assert "**Overall:** 🟩 VERIFIED" in board
    assert "**Observed verification:** 100%" in board


def test_unexpected_skip_prevents_verified_status() -> None:
    class UnexpectedSkipBot(FakeBot):
        def _request(self, method: str, path: str):
            if path == "/repos/owner/repo":
                return {"default_branch": "main"}
            if path == "/repos/owner/repo/branches/main":
                return {"commit": {"sha": "unexpected123456"}}
            if "head_sha=unexpected123456" in path:
                return {
                    "workflow_runs": [
                        {
                            "name": "Build and Verify",
                            "status": "completed",
                            "conclusion": "skipped",
                        }
                    ]
                }
            raise AssertionError(path)

    board = build_status_board(UnexpectedSkipBot(), {"issue": {"number": 10}})
    assert "**Build and Verify** — UNEXPECTED_SKIP" in board
    assert "**Overall:** 🟥 ACTION NEEDED" in board
    assert "**Observed verification:** 0%" in board


def test_pull_request_status_uses_exact_head_sha() -> None:
    class PrBot(FakeBot):
        def _request(self, method: str, path: str):
            self.calls.append(path)
            if path == "/repos/owner/repo/pulls/42":
                return {"head": {"ref": "feature/demo", "sha": "abcdef1234567890"}}
            if "head_sha=abcdef1234567890" in path:
                return {
                    "workflow_runs": [
                        {
                            "name": "Build and Verify",
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

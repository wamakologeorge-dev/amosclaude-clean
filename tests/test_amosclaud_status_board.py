from amosclaud_bot.status_board import build_status_board, is_status_request


class FakeBot:
    repository = "owner/repo"

    def __init__(self) -> None:
        self.calls: list[str] = []

    def _request(self, method: str, path: str):
        self.calls.append(path)
        if path == "/repos/owner/repo":
            return {"default_branch": "main"}
        if path.startswith("/repos/owner/repo/actions/runs?"):
            return {
                "workflow_runs": [
                    {"name": "Amosclaud AI", "status": "completed", "conclusion": "success"},
                    {"name": "Amosclaud Autonomous", "status": "completed", "conclusion": "failure"},
                    {"name": "CodeQL", "status": "in_progress", "conclusion": None},
                ]
            }
        raise AssertionError(path)


def test_status_aliases_are_explicit() -> None:
    assert is_status_request("@amosclaud status")
    assert is_status_request("@amosclaud-status")
    assert is_status_request("Amosclaud-status")
    assert not is_status_request("@amosclaud inspect repository")


def test_status_board_uses_real_workflow_run_results() -> None:
    bot = FakeBot()
    board = build_status_board(bot, {"issue": {"number": 7}})

    assert "🟩 **Amosclaud AI** — PASSED" in board
    assert "🟥 **Amosclaud Autonomous** — FAILED" in board
    assert "🟨 **CodeQL** — RUNNING" in board
    assert "**Overall:** 🟥 ACTION NEEDED" in board
    assert "**Target:** `main`" in board
    assert any("branch=main" in call for call in bot.calls)


def test_all_successful_real_runs_report_ready() -> None:
    class PassingBot(FakeBot):
        def _request(self, method: str, path: str):
            if path == "/repos/owner/repo":
                return {"default_branch": "main"}
            return {
                "workflow_runs": [
                    {"name": "Amosclaud AI", "status": "completed", "conclusion": "success"},
                    {"name": "Amosclaud Autonomous", "status": "completed", "conclusion": "success"},
                ]
            }

    board = build_status_board(PassingBot(), {"issue": {"number": 8}})
    assert "**Overall:** 🟩 READY" in board

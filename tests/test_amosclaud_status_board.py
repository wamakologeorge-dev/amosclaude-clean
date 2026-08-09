from amosclaud_bot.status_board import build_status_board, is_status_request


def run(
    run_id: int,
    name: str,
    *,
    event: str = "pull_request",
    status: str = "completed",
    conclusion: str | None = "success",
) -> dict[str, object]:
    return {
        "id": run_id,
        "name": name,
        "event": event,
        "status": status,
        "conclusion": conclusion,
    }


def default_required_runs(start: int = 100) -> list[dict[str, object]]:
    return [
        run(start, "Build and Verify"),
        run(start + 1, "Amosclaud CI"),
        run(start + 2, "CodeQL"),
        run(start + 3, "Fortify AST Scan"),
    ]


def pull_request_required_runs(start: int = 200) -> list[dict[str, object]]:
    return [
        run(start, "Fast PR Gate"),
        run(start + 1, "Amosclaud Workflow Policy"),
        run(start + 2, "Build and Verify"),
        run(start + 3, "Amosclaud CI"),
        run(start + 4, "CodeQL"),
        run(start + 5, "Amosclaud Dependency Threat Gate"),
        run(start + 6, "Fortify AST Scan"),
    ]


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
        if "head_sha=mainsha1234567890" in path and "&page=1" in path:
            return {
                "workflow_runs": [
                    run(1, "Amosclaud AI"),
                    run(2, "Amosclaud Autonomous", conclusion="failure"),
                    run(3, "CodeQL", status="in_progress", conclusion=None),
                ]
            }
        raise AssertionError(path)


def test_status_aliases_are_explicit() -> None:
    assert is_status_request("@amosclaud status")
    assert is_status_request("@amosclaud-status")
    assert is_status_request("Amosclaud-status")
    assert not is_status_request("@amosclaud inspect repository")


def test_status_board_uses_exact_commit_and_reports_missing_required_workflows() -> None:
    bot = FakeBot()
    board = build_status_board(bot, {"issue": {"number": 7}})

    assert "🟩 **Amosclaud AI** — PASSED" in board
    assert "🟥 **Amosclaud Autonomous** — FAILED" in board
    assert "🟨 **CodeQL** — PENDING" in board
    assert "🟥 **Build and Verify [required workflow]** — MISSING" in board
    assert "**Overall:** 🟥 ACTION NEEDED" in board
    assert "**Observed verification:** 17%" in board
    assert "**Runs evaluated:** 3" in board
    assert "**Contract checks evaluated:** 6" in board
    assert "**Target:** `main`" in board
    assert "**Commit:** `mainsha12345`" in board
    assert any("head_sha=mainsha1234567890" in call for call in bot.calls)
    assert not any("branch=main" in call for call in bot.calls)


def test_all_configured_workflows_must_succeed_for_verified_100_percent() -> None:
    class PassingBot(FakeBot):
        def _request(self, method: str, path: str):
            if path == "/repos/owner/repo":
                return {"default_branch": "main"}
            if path == "/repos/owner/repo/branches/main":
                return {"commit": {"sha": "passing123456789"}}
            if "head_sha=passing123456789" in path and "&page=1" in path:
                return {"workflow_runs": default_required_runs()}
            raise AssertionError(path)

    board = build_status_board(PassingBot(), {"issue": {"number": 8}})
    assert "**Overall:** 🟩 VERIFIED" in board
    assert "**Observed verification:** 100%" in board
    assert "**Runs evaluated:** 4" in board
    assert "**Contract checks evaluated:** 4" in board


def test_event_specific_conditional_skip_is_allowed_only_for_its_event() -> None:
    class SkippingBot(FakeBot):
        event = "issue_comment"

        def _request(self, method: str, path: str):
            if path == "/repos/owner/repo":
                return {"default_branch": "main"}
            if path == "/repos/owner/repo/branches/main":
                return {"commit": {"sha": "skipsha123456789"}}
            if "head_sha=skipsha123456789" in path and "&page=1" in path:
                return {
                    "workflow_runs": [
                        *default_required_runs(),
                        run(20, "Repository Behavior Automation"),
                        run(
                            21,
                            "cmood Autonomous Agent Trigger",
                            event=self.event,
                            conclusion="skipped",
                        ),
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
    assert "**Observed verification:** 83%" in rejected


def test_fork_fixer_workflow_run_skip_is_expected() -> None:
    class ForkFixerBot(FakeBot):
        def _request(self, method: str, path: str):
            if path == "/repos/owner/repo":
                return {"default_branch": "main"}
            if path == "/repos/owner/repo/branches/main":
                return {"commit": {"sha": "forkskip123456"}}
            if "head_sha=forkskip123456" in path and "&page=1" in path:
                return {
                    "workflow_runs": [
                        *default_required_runs(),
                        run(
                            300,
                            "Amosclaud Fork PR Fixer",
                            event="workflow_run",
                            conclusion="skipped",
                        ),
                    ]
                }
            raise AssertionError(path)

    board = build_status_board(ForkFixerBot(), {"issue": {"number": 30}})
    assert "**Amosclaud Fork PR Fixer** — EXPECTED_SKIP" in board
    assert "**Overall:** 🟩 VERIFIED" in board


def test_pull_request_status_requires_independent_workflow_set() -> None:
    class PrBot(FakeBot):
        include_all = True

        def _request(self, method: str, path: str):
            self.calls.append(path)
            if path == "/repos/owner/repo/pulls/42":
                return {"head": {"ref": "feature/demo", "sha": "abcdef1234567890"}}
            if "head_sha=abcdef1234567890" in path and "&page=1" in path:
                workflows = pull_request_required_runs()
                if not self.include_all:
                    workflows = [item for item in workflows if item["name"] != "CodeQL"]
                return {"workflow_runs": workflows}
            raise AssertionError(path)

    bot = PrBot()
    board = build_status_board(bot, {"issue": {"number": 42, "pull_request": {"url": "x"}}})
    assert "🟩 **Build and Verify** — PASSED" in board
    assert "**Overall:** 🟩 VERIFIED" in board
    assert "**Target:** `feature/demo`" in board
    assert any("head_sha=abcdef1234567890" in call for call in bot.calls)

    missing_bot = PrBot()
    missing_bot.include_all = False
    missing = build_status_board(
        missing_bot,
        {"issue": {"number": 42, "pull_request": {"url": "x"}}},
    )
    assert "**CodeQL [required workflow]** — MISSING" in missing
    assert "**Overall:** 🟥 ACTION NEEDED" in missing


def test_default_branch_with_slash_is_encoded_as_one_path_component() -> None:
    class SlashBranchBot(FakeBot):
        def _request(self, method: str, path: str):
            self.calls.append(path)
            if path == "/repos/owner/repo":
                return {"default_branch": "release/v1"}
            if path == "/repos/owner/repo/branches/release%2Fv1":
                return {"commit": {"sha": "release123456789"}}
            if "head_sha=release123456789" in path and "&page=1" in path:
                return {"workflow_runs": default_required_runs()}
            raise AssertionError(path)

    bot = SlashBranchBot()
    board = build_status_board(bot, {"issue": {"number": 31}})
    assert "**Target:** `release/v1`" in board
    assert any(path.endswith("/branches/release%2Fv1") for path in bot.calls)


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
            if "head_sha=repeated123456789" in path and "&page=1" in path:
                return {
                    "workflow_runs": [
                        *default_required_runs(),
                        run(41, "Amosclaud Agent Main", event="workflow_run"),
                        run(
                            40,
                            "Amosclaud Agent Main",
                            event="workflow_run",
                            conclusion="failure",
                        ),
                    ]
                }
            raise AssertionError(path)

    board = build_status_board(RepeatedBot(), {"issue": {"number": 12}})

    assert board.count("**Amosclaud Agent Main**") == 2
    assert "**Amosclaud Agent Main** — PASSED" in board
    assert "**Amosclaud Agent Main** — FAILED" in board
    assert "**Overall:** 🟥 ACTION NEEDED" in board
    assert "**Observed verification:** 83%" in board


def test_pagination_includes_failures_beyond_the_first_hundred_runs() -> None:
    class PaginatedBot(FakeBot):
        def _request(self, method: str, path: str):
            self.calls.append(path)
            if path == "/repos/owner/repo":
                return {"default_branch": "main"}
            if path == "/repos/owner/repo/branches/main":
                return {"commit": {"sha": "paged1234567890"}}
            if "head_sha=paged1234567890" in path and "&page=1" in path:
                return {
                    "workflow_runs": [
                        run(1000 + index, f"Passing workflow {index}") for index in range(100)
                    ]
                }
            if "head_sha=paged1234567890" in path and "&page=2" in path:
                return {"workflow_runs": [run(2001, "Late failing workflow", conclusion="failure")]}
            raise AssertionError(path)

    bot = PaginatedBot()
    board = build_status_board(bot, {"issue": {"number": 13}})

    assert "**Overall:** 🟥 ACTION NEEDED" in board
    assert "**Runs evaluated:** 101" in board
    assert "**Contract checks evaluated:** 105" in board
    assert "81 additional contract check(s)" in board
    assert any("&page=2" in call for call in bot.calls)

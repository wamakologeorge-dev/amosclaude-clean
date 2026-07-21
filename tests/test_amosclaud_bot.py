from amosclaud_bot import bot as bot_module
from amosclaud_bot.bot import AmosclaudBot, parse_command


class FakeKernel:
    def status(self):
        return {"status": "ready", "workspace": "/repo"}

    def execute(self, *, objective, mode, authorized_writes, metadata):
        return {
            "status": "completed",
            "evidence": [f"Autonomous executed {mode}: {objective}"],
            "changed_files": [],
        }

    def repair(self, *, issue, authorized_writes):
        assert authorized_writes is True
        return {
            "status": "completed",
            "evidence": [f"Fixer repaired: {issue}"],
            "changed_files": ["app.py"],
        }


def install_fake_kernel(monkeypatch):
    kernel = FakeKernel()
    monkeypatch.setattr(bot_module, "get_autonomous_kernel", lambda workspace: kernel)
    return kernel


def test_parse_command_supports_primary_bot_name():
    assert parse_command("@amosclaud inspect failing CI") == ("inspect", "failing CI")


def test_parse_command_supports_bot_alias_and_defaults_to_help():
    assert parse_command("@amosclaud-bot") == ("help", "")


def test_unrelated_comment_is_ignored():
    assert parse_command("please inspect this") == (None, "")


def test_status_reports_repository_local_runtime(monkeypatch):
    install_fake_kernel(monkeypatch)
    bot = AmosclaudBot("owner/repo")
    payload = {
        "comment": {"body": "@amosclaud status", "author_association": "NONE"},
        "issue": {"number": 42, "pull_request": {"url": "https://example.invalid/pr"}},
    }
    response = bot.handle_comment(payload)
    assert response.should_comment is True
    assert "GitHub Actions runner: **ready**" in response.body
    assert "Website dependency: **none**" in response.body
    assert "Amosclaud Autonomous: **ready**" in response.body
    assert "Amosclaud-Fixer: **available" in response.body


def test_inspect_routes_to_local_autonomous(monkeypatch):
    install_fake_kernel(monkeypatch)
    bot = AmosclaudBot("owner/repo")
    response = bot.handle_comment(
        {
            "comment": {"body": "@amosclaud inspect failing CI", "author_association": "NONE"},
            "issue": {"number": 7},
        }
    )
    assert "Engine:** Amosclaud Autonomous" in response.body
    assert "Autonomous executed plan: failing CI" in response.body


def test_fix_from_untrusted_user_is_blocked(monkeypatch):
    install_fake_kernel(monkeypatch)
    bot = AmosclaudBot("owner/repo")
    response = bot.handle_comment(
        {
            "comment": {"body": "@amosclaud fix CI failure", "author_association": "NONE"},
            "issue": {"number": 7},
        }
    )
    assert "Engine:** Amosclaud-Fixer" in response.body
    assert "write_not_authorized" in response.body


def test_fix_from_trusted_collaborator_routes_to_fixer(monkeypatch):
    install_fake_kernel(monkeypatch)
    bot = AmosclaudBot("owner/repo")
    response = bot.handle_comment(
        {
            "comment": {"body": "@amosclaud fix CI failure", "author_association": "OWNER"},
            "issue": {"number": 7},
        }
    )
    assert "Engine:** Amosclaud-Fixer" in response.body
    assert "Fixer repaired: CI failure" in response.body
    assert "`app.py`" in response.body


def test_failed_workflow_run_targets_linked_pull_request():
    bot = AmosclaudBot("owner/repo")
    number, response = bot.handle_workflow_run(
        {
            "workflow_run": {
                "conclusion": "failure",
                "name": "CI/CD — Test & Deploy",
                "html_url": "https://example.invalid/run/1",
                "pull_requests": [{"number": 11}],
            }
        }
    )
    assert number == 11
    assert response.should_comment is True
    assert "detected a CI failure" in response.body
    assert "Amosclaud-Fixer" in response.body

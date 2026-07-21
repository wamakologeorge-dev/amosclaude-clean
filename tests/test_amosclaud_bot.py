from amosclaud_bot.bot import AmosclaudBot, parse_command


def test_parse_command_supports_primary_bot_name():
    assert parse_command("@amosclaud inspect failing CI") == ("inspect", "failing CI")


def test_parse_command_supports_bot_alias_and_defaults_to_help():
    assert parse_command("@amosclaud-bot") == ("help", "")


def test_unrelated_comment_is_ignored():
    assert parse_command("please inspect this") == (None, "")


def test_status_reports_github_bot_ready(monkeypatch):
    monkeypatch.delenv("AMOSCLAUD_BOT_AUTONOMOUS_ENDPOINT", raising=False)
    bot = AmosclaudBot("owner/repo")
    payload = {
        "comment": {"body": "@amosclaud status"},
        "issue": {"number": 42, "pull_request": {"url": "https://example.invalid/pr"}},
    }
    response = bot.handle_comment(payload)
    assert response.should_comment is True
    assert "GitHub event handling: **ready**" in response.body
    assert "pull request #42" in response.body


def test_fix_without_endpoint_is_truthful(monkeypatch):
    monkeypatch.delenv("AMOSCLAUD_BOT_AUTONOMOUS_ENDPOINT", raising=False)
    bot = AmosclaudBot("owner/repo")
    payload = {
        "comment": {"body": "@amosclaud fix CI failure"},
        "issue": {"number": 7},
    }
    response = bot.handle_comment(payload)
    assert "autonomous write execution is not connected yet" in response.body
    assert "AMOSCLAUD_BOT_AUTONOMOUS_ENDPOINT" in response.body


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

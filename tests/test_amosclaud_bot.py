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


def test_natural_language_write_request_routes_to_fixer():
    assert parse_command("@amosclaud create a health check file and test it") == (
        "fix",
        "create a health check file and test it",
    )


def test_natural_language_problem_routes_to_autonomous_inspection():
    assert parse_command("@amosclaud my tests started failing after the last merge") == (
        "inspect",
        "my tests started failing after the last merge",
    )


def test_natural_language_review_routes_to_review():
    assert parse_command("@amosclaud review this PR and tell me what is risky") == (
        "review",
        "this PR and tell me what is risky",
    )


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
    assert "Operation bucket bridge: **shared execution core enabled**" in response.body
    assert "Website dependency: **optional; GitHub mode remains independent**" in response.body
    assert "Amosclaud Autonomous: **ready**" in response.body
    assert "Amosclaud-Fixer: **available" in response.body
    assert "Natural-language assistant mode: **enabled**" in response.body


def test_inspect_routes_to_local_autonomous_and_returns_structured_report(monkeypatch, tmp_path):
    install_fake_kernel(monkeypatch)
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "ci.yml").write_text("name: CI\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_sample.py").write_text("def test_ok(): assert True\n", encoding="utf-8")
    (tmp_path / "SECURITY.md").write_text("# Security\n", encoding="utf-8")
    (tmp_path / ".github" / "dependabot.yml").write_text("version: 2\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\n[tool.ruff]\n", encoding="utf-8")

    bot = AmosclaudBot("owner/repo", workspace=tmp_path)
    response = bot.handle_comment(
        {
            "comment": {"body": "@amosclaud inspect this repository", "author_association": "NONE"},
            "issue": {"number": 7},
        }
    )
    assert "Amosclaud Autonomous Assistant — Inspect" in response.body
    assert "Engine:** Amosclaud Autonomous" in response.body
    assert "Status:** **COMPLETED**" in response.body
    assert "Repository findings" in response.body
    assert "1. CI/CD" in response.body
    assert "2. Tests" in response.body
    assert "3. Security" in response.body
    assert "4. Code quality" in response.body
    assert "Priority" in response.body
    assert "Recommended next action" in response.body


def test_inspection_does_not_follow_symlink_outside_repository(monkeypatch, tmp_path):
    install_fake_kernel(monkeypatch)
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    (outside / "test_escape.py").write_text("raise RuntimeError('must not be scanned')\n", encoding="utf-8")
    (tmp_path / "linked-tests").symlink_to(outside, target_is_directory=True)

    bot = AmosclaudBot("owner/repo", workspace=tmp_path)
    response = bot.handle_comment(
        {
            "comment": {"body": "@amosclaud inspect repository", "author_association": "NONE"},
            "issue": {"number": 8},
        }
    )

    assert "0 Python test file(s) were detected" in response.body


def test_safe_relative_file_rejects_parent_traversal(tmp_path):
    root, owner_uid = bot_module._inspection_root(tmp_path)
    assert bot_module._safe_relative_file(root, "../secret.txt", owner_uid) is None


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
    assert "Autonomous brain:" in response.body
    assert "outcome recorded as success" in response.body


def test_natural_language_create_from_owner_routes_to_fixer(monkeypatch):
    install_fake_kernel(monkeypatch)
    bot = AmosclaudBot("owner/repo")
    response = bot.handle_comment(
        {
            "comment": {
                "body": "@amosclaud create a health check file and test it",
                "author_association": "OWNER",
            },
            "issue": {"number": 9},
        }
    )
    assert "Autonomous Assistant — Fix" in response.body
    assert "Fixer repaired: create a health check file and test it" in response.body


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
    assert "Tell me naturally" in response.body

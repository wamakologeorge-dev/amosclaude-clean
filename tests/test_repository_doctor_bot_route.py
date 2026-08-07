from __future__ import annotations

from types import SimpleNamespace

from amosclaud_bot import repository_doctor


def payload(command: str, *, association: str = "OWNER", pull_request: bool = True):
    issue = {"number": 973}
    if pull_request:
        issue["pull_request"] = {"url": "https://api.github.test/pulls/973"}
    return {
        "comment": {
            "body": command,
            "author_association": association,
        },
        "issue": issue,
    }


class FakeBot:
    def __init__(self):
        self.repository = "owner/repository"
        self.token = "token"
        self.comments: list[tuple[int, str]] = []
        self.requests: list[tuple[str, str, object]] = []

    def post_comment(self, issue_number: int, body: str) -> None:
        self.comments.append((issue_number, body))

    def _request(self, method: str, path: str, body=None):
        self.requests.append((method, path, body))
        if method == "GET":
            return {"default_branch": "main"}
        return {}


def test_parse_trusted_pull_request_slash_commands():
    for command, expected in repository_doctor.SLASH_COMMANDS.items():
        operation, number, trusted = repository_doctor.parse_slash_command(
            payload(command)
        )
        assert operation == expected
        assert number == 973
        assert trusted is True


def test_untrusted_or_non_pr_slash_command_is_ignored():
    operation, number, trusted = repository_doctor.parse_slash_command(
        payload("/amos fix", association="NONE")
    )
    assert operation == "fix"
    assert number == 973
    assert trusted is False

    operation, number, trusted = repository_doctor.parse_slash_command(
        payload("/amos explain", pull_request=False)
    )
    assert operation == "explain"
    assert number is None
    assert trusted is True


def test_explain_and_fix_use_trusted_agent_chat_controller(monkeypatch):
    calls = []

    def post_or_update_comment(*args):
        calls.append(("comment", args))

    def latest_run_for_pull_request(*args):
        calls.append(("latest", args))
        return {"id": 123, "name": "Fast PR Gate", "conclusion": "failure"}

    def run_doctor(**kwargs):
        calls.append(("doctor", kwargs))
        return SimpleNamespace()

    controller = SimpleNamespace(
        post_or_update_comment=post_or_update_comment,
        latest_run_for_pull_request=latest_run_for_pull_request,
        run_doctor=run_doctor,
    )
    monkeypatch.setattr(repository_doctor, "_load_agent_chat", lambda: controller)

    bot = FakeBot()
    assert repository_doctor.handle_repository_doctor_command(
        bot, payload("/amos explain")
    ) == 0
    explain = [item for item in calls if item[0] == "doctor"][-1][1]
    assert explain["dispatch"] is False
    assert explain["comment"] is True

    assert repository_doctor.handle_repository_doctor_command(
        bot, payload("/amos fix")
    ) == 0
    repair = [item for item in calls if item[0] == "doctor"][-1][1]
    assert repair["dispatch"] is True
    assert repair["comment"] is True


def test_scan_dispatches_existing_read_only_workflow():
    bot = FakeBot()
    assert repository_doctor.handle_repository_doctor_command(
        bot, payload("/amos scan")
    ) == 0

    dispatch = [request for request in bot.requests if request[0] == "POST"]
    assert len(dispatch) == 1
    method, path, body = dispatch[0]
    assert method == "POST"
    assert path.endswith("/actions/workflows/scan.yml/dispatches")
    assert body["ref"] == "main"
    assert body["inputs"]["pull_request_number"] == "973"
    assert bot.comments
    assert "read-only line scanner" in bot.comments[-1][1]


def test_dispatcher_handles_doctor_before_professional_execution():
    source = repository_doctor.Path(
        repository_doctor.__file__
    ).with_name("dispatcher.py").read_text(encoding="utf-8")
    doctor_position = source.index("handle_repository_doctor_command(bot, payload)")
    professional_position = source.index("return run_professional_from_environment()")
    assert doctor_position < professional_position
    assert 'PRIVATE_ROUTE_MARKER.write_text("repository-doctor\\n"' in source

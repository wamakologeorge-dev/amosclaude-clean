from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys
import types


if "github" not in sys.modules:
    github_stub = types.ModuleType("github")
    github_stub.Github = object
    sys.modules["github"] = github_stub


def load_reviewer():
    path = Path(__file__).parents[1] / ".github" / "scripts" / "ai_reviewer.py"
    spec = spec_from_file_location("ai_reviewer", path)
    assert spec and spec.loader
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


reviewer = load_reviewer()


def test_environment_managed_tokens_and_placeholders_are_not_credentials():
    diff = """
+GITHUB_TOKEN: ${{ secrets.AMOSCLAUD_GITHUB_TOKEN }}
+token_expr = "${{ secrets.AMOSCLAUD_GITHUB_TOKEN || github.token }}"
+environment = {"AMOSCLAUD_GITHUB_TOKEN": "masked-test-token"}
"""
    findings = reviewer.review_diff(diff)
    assert not any("hard-coded credential" in item for item in findings)


def test_real_literal_token_is_reported():
    diff = '+API_KEY = "github_pat_A1b2C3d4E5f6G7h8I9j0K1l2"\n'
    findings = reviewer.review_diff(diff)
    assert any("hard-coded credential" in item for item in findings)


def test_fixed_argument_subprocess_is_not_shell_execution():
    diff = "+subprocess.run(['git', 'diff', '--check'], check=False)\n"
    findings = reviewer.review_diff(diff)
    assert not any("command execution" in item.lower() for item in findings)


def test_shell_execution_is_reported():
    diff = "+subprocess.run(user_command, shell=True, check=True)\n"
    findings = reviewer.review_diff(diff)
    assert any("shell-based command execution" in item.lower() for item in findings)


class FakeComment:
    def __init__(self, body, *, fail_edit=False):
        self.body = body
        self.fail_edit = fail_edit
        self.edits = []
        self.deleted = False

    def edit(self, body):
        if self.fail_edit:
            raise PermissionError("comment belongs to another GitHub identity")
        self.body = body
        self.edits.append(body)

    def delete(self):
        self.deleted = True


class FakePull:
    def __init__(self, comments):
        self.comments = comments
        self.created = []

    def get_issue_comments(self):
        return list(self.comments)

    def create_issue_comment(self, body):
        created = FakeComment(body)
        self.created.append(body)
        self.comments.append(created)
        return created


def test_publish_review_updates_one_comment_and_removes_duplicates():
    old = FakeComment("### Amosclaud automated review\n\nOld")
    latest = FakeComment(
        "<!-- amosclaud-automated-review -->\n"
        "### Amosclaud automated review\n\nLatest"
    )
    pull = FakePull([old, latest])
    body = reviewer.build_comment([])

    reviewer.publish_comment(pull, body)

    assert pull.created == []
    assert latest.edits == [body]
    assert old.deleted is True


def test_publish_review_recreates_comment_owned_by_another_identity():
    old = FakeComment(
        "### Amosclaud automated review\n\nOld",
        fail_edit=True,
    )
    pull = FakePull([old])
    body = reviewer.build_comment([])

    reviewer.publish_comment(pull, body)

    assert pull.created == [body]
    assert old.deleted is True


def test_publish_with_tokens_uses_scoped_fallback():
    calls = []
    pull = FakePull([])

    class FakeRepo:
        def get_pull(self, number):
            assert number == 737
            return pull

    class FakeGithub:
        def __init__(self, token):
            self.token = token
            calls.append(token)

        def get_repo(self, name):
            assert name == "owner/repository"
            if self.token == "primary":
                raise PermissionError("primary token cannot write this comment")
            return FakeRepo()

    delivered = reviewer.publish_with_tokens(
        "owner/repository",
        737,
        "review body",
        ["primary", "fallback", "fallback"],
        github_factory=FakeGithub,
    )

    assert delivered is True
    assert calls == ["primary", "fallback"]
    assert pull.created == ["review body"]

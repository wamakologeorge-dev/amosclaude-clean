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
    def __init__(self, body):
        self.body = body
        self.edits = []
        self.deleted = False

    def edit(self, body):
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
        self.created.append(body)


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

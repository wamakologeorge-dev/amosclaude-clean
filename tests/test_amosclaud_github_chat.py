from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHAT = ROOT / ".github" / "scripts" / "amosclaud_github_chat.py"
WORKFLOW = ROOT / ".github" / "workflows" / "amosclaud-github-chat.yml"
TEMPLATE = ROOT / ".github" / "ISSUE_TEMPLATE" / "amosclaud-chat.yml"


def _load():
    spec = importlib.util.spec_from_file_location("amosclaud_github_chat_contract", CHAT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_chat_trigger_accepts_command_and_mention() -> None:
    module = _load()
    assert module.parse_trigger("/amosclaud explain this") == "explain this"
    assert module.parse_trigger("@amosclaud status") == "status"
    assert module.parse_trigger("normal comment") is None


def test_chat_issue_title_activates_without_label() -> None:
    module = _load()
    assert module.is_chat_issue({"title": "[Amosclaud Chat] Repository help", "labels": []})
    assert not module.is_chat_issue({"title": "Normal issue", "labels": []})


def test_chat_redacts_credentials() -> None:
    module = _load()
    text = "Authorization: Bearer abcdefghijklmnop token=github_pat_supersecretvalue"
    redacted = module.redact(text)
    assert "abcdefghijklmnop" not in redacted
    assert "github_pat_supersecretvalue" not in redacted
    assert "[REDACTED]" in redacted


def test_outbound_url_validation_blocks_non_http_schemes() -> None:
    module = _load()
    assert module.validate_http_url("https://example.com/api", label="test") == (
        "https://example.com/api"
    )
    for unsafe in (
        "file:///tmp/secret",
        "ftp://example.com/resource",
        "custom://example.com/resource",
        "https://user:password@example.com/api",
    ):
        try:
            module.validate_http_url(unsafe, label="test")
        except module.ChatError:
            pass
        else:
            raise AssertionError(f"unsafe outbound URL was accepted: {unsafe}")


def test_chat_history_preserves_agent_role() -> None:
    module = _load()
    issue = {"body": "initial request"}
    comments = [
        {"body": "/amosclaud first question", "user": {"login": "george"}},
        {
            "body": f"{module.CHAT_MARKER}\n### Amosclaud Agent\n\nfirst answer",
            "user": {"login": "github-actions[bot]", "type": "Bot"},
        },
    ]
    messages = module.conversation_messages(issue, comments, "second question")
    assert [item["role"] for item in messages] == ["user", "user", "assistant", "user"]
    assert messages[-1]["content"] == "second question"


def test_fix_requires_trusted_repository_user(monkeypatch) -> None:
    module = _load()
    issue = {"number": 9, "pull_request": {"url": "https://api.github.com/repos/o/r/pulls/9"}}
    try:
        module.dispatch_fix("token", "o/r", issue, objective="fix tests", association="NONE")
    except module.ChatError as exc:
        assert "restricted" in str(exc)
    else:
        raise AssertionError("untrusted user was allowed to dispatch a repair")


def test_fix_dispatch_pins_exact_pr_sha(monkeypatch) -> None:
    module = _load()
    calls = []

    def fake_api(token, path, *, method="GET", payload=None):
        calls.append((method, path, payload))
        if path == "/repos/o/r/pulls/9":
            return {
                "state": "open",
                "head": {"sha": "abc123", "repo": {"full_name": "o/r"}},
            }
        if path == "/repos/o/r":
            return {"default_branch": "main"}
        if path.endswith("/dispatches"):
            return {}
        raise AssertionError(path)

    monkeypatch.setattr(module, "api_json", fake_api)
    issue = {"number": 9, "pull_request": {"url": "x"}}
    result = module.dispatch_fix("token", "o/r", issue, objective="fix tests", association="OWNER")
    dispatch = calls[-1]
    assert dispatch[0] == "POST"
    assert dispatch[2]["inputs"]["pull_request_number"] == "9"
    assert dispatch[2]["inputs"]["target_sha"] == "abc123"
    assert "exact revision `abc123`" in result


def test_workflow_uses_default_branch_and_never_executes_comment_text() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    assert "ref: ${{ github.event.repository.default_branch }}" in source
    assert "python .github/scripts/amosclaud_github_chat.py" in source
    assert "${{ github.event.comment.body }}" not in source
    assert "contents: read" in source
    assert "actions: write" in source


def test_issue_form_creates_dedicated_chat_thread() -> None:
    source = TEMPLATE.read_text(encoding="utf-8")
    assert "amosclaud-chat" in source
    assert "Amosclaud Agent Chat" in source
    assert "/amosclaud <question>" in source

from pathlib import Path


def test_legacy_issue_bot_is_opt_in_and_does_not_own_amosclaud_commands() -> None:
    workflow = Path('.github/workflows/issue-bot.yml').read_text(encoding='utf-8')

    assert "startsWith(github.event.comment.body, '@amosclaude-ai')" in workflow
    assert "startsWith(github.event.comment.body, '@amosclaud')" not in workflow
    assert "startsWith(github.event.comment.body, '@amosclaud-bot')" not in workflow


def test_canonical_amosclaud_workflow_remains_present() -> None:
    workflow = Path('.github/workflows/amosclaud-bot.yml').read_text(encoding='utf-8')

    assert 'name: Amosclaud Bot' in workflow
    assert 'issue_comment:' in workflow
    assert 'python -m amosclaud_bot.dispatcher' in workflow

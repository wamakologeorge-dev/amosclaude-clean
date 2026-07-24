from pathlib import Path

import pytest

from amoscloud_ai.amo_lang import AmoRuntime, AmoSyntaxError, parse_amo
from amoscloud_ai.core.command_agent import AmosclaudCommandAgent
from amoscloud_ai.core.workspace import WorkspaceEngine


def test_amo_program_declares_capabilities_and_writes_file(tmp_path: Path):
    workspace = WorkspaceEngine(tmp_path / "workspace")
    program = parse_amo(
        '\n'.join(
            [
                'amo 1',
                'agent "Builder"',
                'goal "Create a project note"',
                'allow workspace.write',
                'allow agent.respond',
                'write "notes/result.txt" "created by Amo"',
                'say "done"',
            ]
        )
    )

    result = AmoRuntime(workspace).execute(program)

    assert (workspace.root / "notes" / "result.txt").read_text(encoding="utf-8") == "created by Amo"
    assert result["output"] == ["done"]
    assert [item["opcode"] for item in result["trace"]] == ["write", "say"]


def test_amo_runtime_rejects_missing_capability(tmp_path: Path):
    workspace = WorkspaceEngine(tmp_path / "workspace")
    program = parse_amo('amo 1\nwrite "notes/blocked.txt" "no"')

    with pytest.raises(PermissionError, match="workspace.write"):
        AmoRuntime(workspace).execute(program)


def test_amo_parser_rejects_unknown_instruction():
    with pytest.raises(AmoSyntaxError, match="unknown instruction"):
        parse_amo("amo 1\nshell rm -rf")


def test_command_agent_plans_and_executes_safe_file_instruction(tmp_path: Path):
    workspace = WorkspaceEngine(tmp_path / "workspace")
    agent = AmosclaudCommandAgent(workspace)
    plan = agent.plan('Write file "notes/vision.txt" with Amosclaud belongs to its users')

    assert plan.steps[0].action == "workspace.write"
    result = agent.execute(plan)

    assert result["status"] == "completed"
    assert (workspace.root / "notes" / "vision.txt").read_text(encoding="utf-8") == "Amosclaud belongs to its users"


def test_command_agent_blocks_commit_and_pull_request_without_confirmation(tmp_path: Path):
    agent = AmosclaudCommandAgent(WorkspaceEngine(tmp_path / "workspace"))
    plan = agent.plan("Run tests, commit the changes, and open a pull request")
    result = agent.execute(plan)

    blocked = {item["action"] for item in result["blocked"]}
    assert blocked == {"tests.run", "git.commit", "github.pull_request"}
    assert result["status"] == "partial"


def test_command_agent_never_allows_workspace_escape(tmp_path: Path):
    agent = AmosclaudCommandAgent(WorkspaceEngine(tmp_path / "workspace"))
    plan = agent.plan('Write file "../outside.txt" with forbidden')
    result = agent.execute(plan)

    assert result["completed"][0]["status"] == "failed"
    assert not (tmp_path / "outside.txt").exists()


def test_command_agent_does_not_scan_write_content_for_actions(tmp_path: Path):
    agent = AmosclaudCommandAgent(WorkspaceEngine(tmp_path / "workspace"))

    plan = agent.plan(
        'Write file "notes/message.txt" with Please read file "notes/secret.txt"'
    )

    assert [step.action for step in plan.steps] == ["workspace.write"]


def test_command_agent_preserves_multiline_file_content(tmp_path: Path):
    workspace = WorkspaceEngine(tmp_path / "workspace")
    agent = AmosclaudCommandAgent(workspace)
    content = "first line\nsecond line"
    plan = agent.plan(f'Write file "notes/multiline.txt" with {content}')

    result = agent.execute(plan)

    assert result["status"] == "completed"
    assert (workspace.root / "notes" / "multiline.txt").read_text(encoding="utf-8") == content

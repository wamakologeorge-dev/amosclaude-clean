import json
from pathlib import Path

import pytest

from amoscloud_ai.amo_lang import AmoRuntime, AmoSyntaxError, parse_amo
from amoscloud_ai.core.workspace import WorkspaceEngine, WorkspaceError


def test_amo_program_executes_as_agent(tmp_path: Path):
    source = '''
amo 1
agent "Builder"
goal "Respond from one agent-language program"
allow agent.respond
remember greeting "Hello"
say "{{greeting}}, {{input}}"
'''
    program = parse_amo(source)
    runtime = AmoRuntime(WorkspaceEngine(tmp_path / "workspace"))

    result = runtime.execute(program, input_text="George")

    assert result["agent"] == "Builder"
    assert result["output"] == ["Hello, George"]
    assert result["trace"][0]["status"] == "completed"


def test_amo_requires_declared_capability(tmp_path: Path):
    program = parse_amo('''
amo 1
agent "Restricted"
say "Not allowed"
''')
    runtime = AmoRuntime(WorkspaceEngine(tmp_path / "workspace"))

    with pytest.raises(PermissionError, match="agent.respond"):
        runtime.execute(program)


def test_amo_reads_and_writes_only_inside_workspace(tmp_path: Path):
    workspace = WorkspaceEngine(tmp_path / "workspace")
    program = parse_amo('''
amo 1
agent "Writer"
allow workspace.write
allow workspace.read
allow agent.respond
write "notes/runtime.txt" "Amo remembers {{input}}"
read "notes/runtime.txt" "saved"
say "{{saved}}"
''')

    result = AmoRuntime(workspace).execute(program, input_text="safely")

    assert result["output"] == ["Amo remembers safely"]
    assert (workspace.root / "notes" / "runtime.txt").read_text() == "Amo remembers safely"


def test_amo_rejects_path_escape(tmp_path: Path):
    workspace = WorkspaceEngine(tmp_path / "workspace")
    program = parse_amo('''
amo 1
agent "Escape"
allow workspace.write
write "../outside.txt" "blocked"
''')

    with pytest.raises(Exception, match="Invalid workspace path"):
        AmoRuntime(workspace).execute(program)


def test_amo_rejects_unknown_capability():
    with pytest.raises(AmoSyntaxError, match="unsupported capability"):
        parse_amo('''
amo 1
allow shell.root
''')


def test_amo_requires_version_header_first():
    with pytest.raises(AmoSyntaxError, match="must begin"):
        parse_amo('allow workspace.write\namo 1\nwrite "notes/x" "bad"')


def test_amo_does_not_apply_late_capability_grants(tmp_path: Path):
    program = parse_amo('amo 1\nwrite "notes/x" "blocked"\nallow workspace.write')
    runtime = AmoRuntime(WorkspaceEngine(tmp_path / "workspace"))

    with pytest.raises(PermissionError, match="workspace.write"):
        runtime.execute(program)


def test_amo_reads_invalid_json_as_raw_text(tmp_path: Path):
    workspace = WorkspaceEngine(tmp_path / "workspace")
    path = workspace.root / "notes" / "draft.json"
    path.write_text('{"unfinished":', encoding="utf-8")
    program = parse_amo(
        'amo 1\nallow workspace.read\nallow memory.read\n'
        'read "notes/draft.json" "draft"\nrecall "draft"'
    )

    result = AmoRuntime(workspace).execute(program)

    assert result["output"] == ['{"unfinished":']


def test_amo_records_failed_partial_execution(tmp_path: Path):
    workspace = WorkspaceEngine(tmp_path / "workspace")
    program = parse_amo(
        'amo 1\nallow workspace.write\n'
        'write "notes/created.txt" "created"\n'
        'write "../outside.txt" "blocked"'
    )

    with pytest.raises(WorkspaceError, match="Invalid workspace path"):
        AmoRuntime(workspace).execute(program)

    events = [
        json.loads(line)
        for line in (workspace.root / "logs" / "activity.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert events[-1]["status"] == "failed"
    assert [item["status"] for item in events[-1]["trace"]] == ["completed", "failed"]

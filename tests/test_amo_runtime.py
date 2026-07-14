from pathlib import Path

import pytest

from amoscloud_ai.amo_lang import AmoRuntime, AmoSyntaxError, parse_amo
from amoscloud_ai.core.workspace import WorkspaceEngine


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

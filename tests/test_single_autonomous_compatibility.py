from pathlib import Path

from amoscloud_ai.agent import CodexAgent
from amoscloud_ai.agentic_cloud_engine import AmosclaudAgenticCloudEngine
from amoscloud_ai.engineering_agent import run_engineering_agent
from src.amosclaud_os.kernel import get_autonomous_kernel


def test_legacy_codex_agent_uses_canonical_kernel(monkeypatch, tmp_path: Path) -> None:
    agent = CodexAgent(tmp_path)
    assert agent.kernel is get_autonomous_kernel(tmp_path)
    assert agent.provider == "amosclaud"

    captured = {}

    def execute(**kwargs):
        captured.update(kwargs)
        return {"status": "passed", "summary": "Command verified", "evidence": ["ok"]}

    monkeypatch.setattr(agent.kernel, "execute", execute)
    code, stdout, stderr = agent.execute_local_command("python -m pytest")
    assert code == 0
    assert stdout == "Command verified"
    assert stderr == ""
    assert captured["mode"] == "test"
    assert captured["authorized_writes"] is False
    assert captured["metadata"]["direct_shell"] is False


def test_legacy_file_actions_require_authorization(monkeypatch, tmp_path: Path) -> None:
    agent = CodexAgent(tmp_path)
    calls = []

    def write_document(path, content, *, authorized_writes=False):
        calls.append((path, content, authorized_writes))
        if not authorized_writes:
            return {"status": "blocked", "error": "write_not_authorized"}
        return {"status": "written", "path": path, "evidence": ["verified"]}

    monkeypatch.setattr(agent.kernel, "write_document", write_document)
    markup = '<write_file path="safe.py">print("safe")</write_file>'

    blocked = agent.parse_and_execute_actions(markup)
    assert blocked[0]["success"] is False
    assert calls[-1][2] is False

    allowed = agent.parse_and_execute_actions(markup, authorized_writes=True)
    assert allowed[0]["success"] is True
    assert calls[-1] == ("safe.py", 'print("safe")', True)


def test_legacy_execute_action_routes_through_kernel(monkeypatch, tmp_path: Path) -> None:
    agent = CodexAgent(tmp_path)
    captured = {}

    def execute(**kwargs):
        captured.update(kwargs)
        return {"status": "passed", "summary": "Tests passed"}

    monkeypatch.setattr(agent.kernel, "execute", execute)
    result = agent.parse_and_execute_actions("<execute>python -m pytest</execute>")
    assert result[0]["success"] is True
    assert result[0]["exit_code"] == 0
    assert captured["metadata"]["direct_shell"] is False


def test_engineering_plan_uses_same_kernel(monkeypatch, tmp_path: Path) -> None:
    kernel = get_autonomous_kernel(tmp_path)
    monkeypatch.setattr(
        kernel,
        "execute",
        lambda **kwargs: {
            "status": "planned",
            "summary": "Plan prepared",
            "evidence": ["bounded"],
            "changed_files": ["app.py"],
        },
    )
    run = run_engineering_agent(tmp_path, "Inspect app.py")
    assert run.applied is False
    assert run.changes[0].status == "planned"
    assert any("AutonomousKernel" in item for item in run.evidence)


def test_cloud_engine_does_not_infer_write_authorization(tmp_path: Path) -> None:
    engine = AmosclaudAgenticCloudEngine(tmp_path)
    result = engine.run("Prepare a repair plan", "fix", {"apply_changes": True})
    assert result.authorized_writes is False
    assert result.status == "blocked"
    assert result.events[0].engine == "amosclaud-autonomous-kernel"

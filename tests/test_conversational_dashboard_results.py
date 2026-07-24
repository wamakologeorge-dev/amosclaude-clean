from pathlib import Path


def test_conversational_agent_streams_real_execution_to_workbench():
    root = Path(__file__).resolve().parents[1]
    script = (root / "web" / "conversational-agent.js").read_text(encoding="utf-8")

    assert "publish('agent-start'" in script
    assert "publish('agent-phase'" in script
    assert "publish('agent-result'" in script
    assert "/api/v1/pipelines/" in script
    assert "jobs.flatMap" in script


def test_every_chat_message_is_routed_through_autonomous():
    root = Path(__file__).resolve().parents[1]
    script = (root / "web" / "conversational-agent.js").read_text(encoding="utf-8")

    assert "fetch('/api/v1/agent/run'" in script
    assert "conversation: conversation.slice(-12)" in script
    assert "single_visible_agent: true" in script
    assert "recordAnswer" not in script
    assert "nextQuestion" not in script
    assert "Success condition:" not in script
    assert "First workflow:" not in script


def test_workbench_renders_results_inline_without_broken_pipeline_page_link():
    root = Path(__file__).resolve().parents[1]
    script = (root / "web" / "live-autonomous-workbench.js").read_text(encoding="utf-8")

    assert "Verified job result" in script
    assert "Execution evidence" in script
    assert "job.logs" in script
    assert "data.pipeline_id) links.unshift" not in script
    assert "Open inside Amosclaud" not in script


def test_dashboard_has_no_fake_result_records():
    root = Path(__file__).resolve().parents[1]
    html = (root / "web" / "index.html").read_text(encoding="utf-8")
    script = (root / "web" / "live-autonomous-workbench.js").read_text(encoding="utf-8")

    forbidden = ("example result", "sample result", "demo result", "fake result")
    content = f"{html}\n{script}".lower()
    for phrase in forbidden:
        assert phrase not in content

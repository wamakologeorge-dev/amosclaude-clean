from pathlib import Path

from src.foundation import AgentsPracticeStation, IntelligentFoundation, UniversalCurriculum


def test_curriculum_spans_assistant_to_autonomous_expert():
    curriculum = UniversalCurriculum()
    assert curriculum.lesson(1).track == "ai-assistant"
    assert curriculum.lesson(1000).track == "codex-engineering"
    assert curriculum.lesson(1750).track == "cloud-agent"
    assert curriculum.lesson(5000).track == "autonomous-expert"


def test_foundation_blocks_write_without_founder_authority(tmp_path: Path):
    (tmp_path / "login.py").write_text("def login():\n    return True\n", encoding="utf-8")
    context = IntelligentFoundation(tmp_path).prepare(
        "fix login and deploy",
        authorized_writes=True,
        founder_verified=False,
        current_level=1000,
    )
    assert "write" in context.blocked_actions
    assert context.simulation is not None
    assert context.next_lesson["level"] == 1001


def test_practice_station_records_verified_practice(tmp_path: Path):
    (tmp_path / "app.py").write_text("print('ok')\n", encoding="utf-8")
    station = AgentsPracticeStation(tmp_path)
    result = station.practice(1000, evidence=["Repository inspected"])
    assert result.track == "codex-engineering"
    assert result.score >= 80
    assert result.promoted is True
    assert station.history()[0]["practice_id"] == result.practice_id

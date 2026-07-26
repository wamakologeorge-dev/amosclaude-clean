from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROGRAM = ROOT / "docs" / "ABSOLUTE_SECURITY_HARDENING.md"
APP = ROOT / "app.py"
APPROVAL_GATE = ROOT / "amosclaud_bot" / "approval_gate.py"


def test_security_program_defines_production_blockers() -> None:
    text = PROGRAM.read_text(encoding="utf-8")

    for required in (
        "owner_user_id",
        "Remove `shell=True`",
        "Celery/Redis or Amosclaud Task Router",
        "dedicated preview service",
        "DNS TXT ownership verification",
        "@amosclaud approve",
    ):
        assert required in text


def test_approval_command_is_single_use_and_owner_bound() -> None:
    gate = APPROVAL_GATE.read_text(encoding="utf-8")

    assert 'normalized.startswith("@amosclaud approve")' in gate
    assert "APPROVAL_CONSUMED_MARKER" in gate
    assert "WRITE_ASSOCIATIONS" in gate
    assert "_approval_source(source_number, objective)" in gate


def test_legacy_dashboard_is_still_a_documented_blocker_until_hardened() -> None:
    app = APP.read_text(encoding="utf-8")
    program = PROGRAM.read_text(encoding="utf-8")

    assert "shell=True" in app
    assert "Legacy workflow dashboard requiring hardening: root `app.py`" in program

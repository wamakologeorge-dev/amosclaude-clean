from pathlib import Path

from amomodel.runtime import AmoModelRuntime
from amoscloud_ai.main import create_app


def test_amomodel_routes_are_registered():
    paths = {getattr(route, "path", "") for route in create_app().routes}
    assert "/api/v1/amomodel/status" in paths
    assert "/api/v1/amomodel/power/on" in paths
    assert "/api/v1/amomodel/power/off" in paths
    assert "/api/v1/amomodel/restart" in paths
    assert "/api/v1/amomodel/execute" in paths


def test_amomodel_persists_truthful_lifecycle(tmp_path: Path):
    state_path = tmp_path / "state.json"
    runtime = AmoModelRuntime(state_path)

    assert runtime.status()["state"] == "off"
    ready = runtime.power_on("tester")
    assert ready["state"] == "ready"
    assert ready["healthy"] is True

    executed = runtime.execute("tester", "Inspect platform readiness")
    assert executed["accepted"] is True
    assert executed["runtime"]["executions"] == 1

    reloaded = AmoModelRuntime(state_path).status()
    assert reloaded["state"] == "ready"
    assert reloaded["executions"] == 1
    assert reloaded["audit"]

    stopped = runtime.power_off("tester")
    assert stopped["state"] == "off"
    assert all(value == "off" for value in stopped["services"].values())


def test_amomodel_never_accepts_empty_objective(tmp_path: Path):
    runtime = AmoModelRuntime(tmp_path / "state.json")
    runtime.power_on("tester")
    try:
        runtime.execute("tester", "   ")
    except ValueError as exc:
        assert "objective" in str(exc)
    else:
        raise AssertionError("empty objective must be rejected")


def test_dashboard_exposes_amomodel_power_controls():
    html = Path("web/index.html").read_text(encoding="utf-8")
    script = Path("web/amomodel-controls.js").read_text(encoding="utf-8")
    assert "Turn on AmoModel" in html
    assert "Turn off AmoModel" in html
    assert "/api/v1/amomodel/status" in script
    assert "/api/v1/amomodel/power/on" in script
    assert "/api/v1/amomodel/power/off" in script

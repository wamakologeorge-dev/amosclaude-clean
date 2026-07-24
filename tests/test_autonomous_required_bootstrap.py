from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_script():
    path = Path(__file__).resolve().parents[1] / "scripts" / "amosclaud_autonomous_required.py"
    spec = importlib.util.spec_from_file_location("amosclaud_autonomous_required", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_manifest_contains_required_autonomous_services():
    module = _load_script()
    expected = {
        "tool_registry.py",
        "mission_store.py",
        "verification_contracts.py",
        "recovery_doctor.py",
        "event_stream.py",
        "model_router.py",
        "memory_store.py",
        "worker.py",
        "connectors.py",
        "audit_replay.py",
        "runtime.py",
    }
    assert expected.issubset(module.FILES)
    assert "src.amosclaud_os.kernel" in module.FILES["runtime.py"]


def test_bootstrap_is_idempotent_and_compiles(tmp_path, monkeypatch):
    module = _load_script()
    package = tmp_path / "src" / "amosclaud_os" / "autonomy"
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "PACKAGE", package)

    created, preserved = module.write_files(force=False)
    assert len(created) == len(module.FILES)
    assert preserved == []
    assert module.compile_files() == []

    created_again, preserved_again = module.write_files(force=False)
    assert created_again == []
    assert len(preserved_again) == len(module.FILES)


def test_generated_runtime_uses_one_kernel():
    module = _load_script()
    runtime = module.FILES["runtime.py"]
    assert "get_autonomous_kernel" in runtime
    assert "AutonomousRequiredRuntime" in runtime

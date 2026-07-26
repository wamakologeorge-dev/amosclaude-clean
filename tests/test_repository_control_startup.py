from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv

from amoscloud_ai.repository_control import initialize_repository_control


CONTROL_MARKERS = (
    "AMOSCLAUD_CONTROL_ACTIVE",
    "AMOSCLAUD_CONTROL_DIR",
    "AMOSCLAUD_CONTROL_SOURCE",
)


def _clear_control_markers() -> None:
    for key in CONTROL_MARKERS:
        os.environ.pop(key, None)


def test_amosclaud_control_environment_loads_before_repository_dotenv(
    tmp_path: Path,
    monkeypatch,
) -> None:
    variable = "AMOSCLAUD_STARTUP_PRIORITY_TEST"
    monkeypatch.delenv(variable, raising=False)
    monkeypatch.delenv("AMOSCLAUD_REPOSITORY_ROOT", raising=False)
    _clear_control_markers()

    control_dir = tmp_path / ".amosclaud"
    control_dir.mkdir()
    (control_dir / "startup.json").write_text(
        json.dumps(
            {
                "priority": 0,
                "environment_files": ["runtime.env"],
                "manifests": ["platform-requirements.json"],
            }
        ),
        encoding="utf-8",
    )
    (control_dir / "runtime.env").write_text(
        f"{variable}=control-first\n",
        encoding="utf-8",
    )
    (control_dir / "platform-requirements.json").write_text(
        json.dumps({"source_of_truth": "amosclaud-native-repository"}),
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text(f"{variable}=repository-env\n", encoding="utf-8")

    try:
        state = initialize_repository_control(start_dir=tmp_path)
        load_dotenv(tmp_path / ".env", override=False)

        assert state.active is True
        assert state.priority == 0
        assert state.source_of_truth == "amosclaud-native-repository"
        assert os.environ[variable] == "control-first"
    finally:
        os.environ.pop(variable, None)
        _clear_control_markers()


def test_process_environment_remains_above_amosclaud_control(
    tmp_path: Path,
    monkeypatch,
) -> None:
    variable = "AMOSCLAUD_STARTUP_HOST_PRIORITY_TEST"
    monkeypatch.setenv(variable, "host-platform")
    monkeypatch.delenv("AMOSCLAUD_REPOSITORY_ROOT", raising=False)
    _clear_control_markers()

    control_dir = tmp_path / ".amosclaud"
    control_dir.mkdir()
    (control_dir / "runtime.env").write_text(
        f"{variable}=control-default\n",
        encoding="utf-8",
    )

    try:
        state = initialize_repository_control(start_dir=tmp_path)
        assert state.active is True
        assert os.environ[variable] == "host-platform"
    finally:
        _clear_control_markers()


def test_package_initializes_repository_control_before_root_dotenv() -> None:
    source = Path("amoscloud_ai/__init__.py").read_text(encoding="utf-8")

    control_position = source.index("REPOSITORY_CONTROL = initialize_repository_control()")
    repository_env_position = source.index("load_dotenv(override=False)")

    assert control_position < repository_env_position
    assert "mutating scripts are never" in source

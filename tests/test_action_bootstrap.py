"""Native Actions must run repositories that declare their own dependencies.

George's api-gateway pull request failed with pytest exit 4 because its
conftest imports the application, the application imports its database layer,
and the database layer needs packages the worker station never installed.
Real CI installs the repository's declared requirements before testing.
These tests pin that contract end to end using a locally built wheel, so
they are hermetic — no network, no index access.
"""

from __future__ import annotations

import os
import shutil
import zipfile
from pathlib import Path

from amoscloud_ai import action_bootstrap, native_actions
from amoscloud_ai.isolated_runner import run_in_isolated_container

REPO_ROOT = Path(__file__).resolve().parents[1]
SANDBOX_ENV = {"PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1"}


def _make_wheel(directory: Path) -> Path:
    """Hand-roll a minimal, valid wheel so installs never touch the network."""

    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "amosdemo-1.0-py3-none-any.whl"
    with zipfile.ZipFile(path, "w") as wheel:
        wheel.writestr("amosdemo/__init__.py", "VALUE = 41\n")
        wheel.writestr(
            "amosdemo-1.0.dist-info/METADATA",
            "Metadata-Version: 2.1\nName: amosdemo\nVersion: 1.0\n",
        )
        wheel.writestr(
            "amosdemo-1.0.dist-info/WHEEL",
            "Wheel-Version: 1.0\nGenerator: amosclaud-tests\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        )
        wheel.writestr(
            "amosdemo-1.0.dist-info/RECORD",
            "amosdemo/__init__.py,,\n"
            "amosdemo-1.0.dist-info/METADATA,,\n"
            "amosdemo-1.0.dist-info/WHEEL,,\n"
            "amosdemo-1.0.dist-info/RECORD,,\n",
        )
    return path


def _gateway_fixture(root: Path) -> None:
    """A repository shaped like the real failure: conftest imports a package
    that only the repository's own requirements provide."""

    _make_wheel(root / "wheels")
    (root / "requirements.txt").write_text(
        "./wheels/amosdemo-1.0-py3-none-any.whl\n", encoding="utf-8"
    )
    gateway = root / "api_gateway"
    gateway.mkdir()
    (gateway / "conftest.py").write_text("import amosdemo\n", encoding="utf-8")
    (gateway / "test_gateway.py").write_text(
        "import amosdemo\n\n\ndef test_dependency_available():\n"
        "    assert amosdemo.VALUE == 41\n",
        encoding="utf-8",
    )
    shutil.copyfile(
        Path(native_actions.__file__).with_name("action_bootstrap.py"),
        root / ".amosclaud-bootstrap.py",
    )


def test_fixed_plan_runs_a_repository_with_its_own_requirements(tmp_path) -> None:
    """Every fixed plan step passes on a dependency-declaring repository."""

    _gateway_fixture(tmp_path)
    outputs: dict[str, str] = {}
    for job_id, _name, command in native_actions.ACTION_PLAN:
        result = run_in_isolated_container(
            command, workspace=tmp_path, environment=SANDBOX_ENV
        )
        outputs[job_id] = result.output
        assert not result.timed_out, f"{job_id} timed out:\n{result.output}"
        assert result.returncode == 0, f"{job_id} failed:\n{result.output}"

    assert "Installing requirements.txt" in outputs["deps"]
    assert "1 passed" in outputs["pytest"]
    assert (tmp_path / action_bootstrap.VENV_DIR / "bin" / "python").exists()


def test_bootstrap_rebuilds_a_committed_environment_directory(tmp_path, monkeypatch) -> None:
    """Repository content can never impersonate the Action environment."""

    fake = tmp_path / action_bootstrap.VENV_DIR / "bin"
    fake.mkdir(parents=True)
    (fake / "python").write_text("#!/bin/sh\necho hijacked\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert action_bootstrap.main() == 0
    real_python = tmp_path / action_bootstrap.VENV_DIR / "bin" / "python"
    assert real_python.exists()
    content = real_python.read_bytes()
    assert b"hijacked" not in content


def test_root_manifests_alone_define_the_environment(tmp_path) -> None:
    """When root-level manifests exist they are installed exclusively: nested
    service manifests (which can reference paths that only exist in their own
    context, or downgrade root pins) and optional variant lanes are skipped,
    and anything inside the Action environment is ignored."""

    (tmp_path / "requirements.txt").write_text("# root\n", encoding="utf-8")
    (tmp_path / "dev-requirements.txt").write_text("# dev\n", encoding="utf-8")
    (tmp_path / "requirements-model-server.txt").write_text(
        "torch>=2\n", encoding="utf-8"
    )
    gateway = tmp_path / "api-gateway"
    gateway.mkdir()
    (gateway / "requirements.txt").write_text("-e ..\n", encoding="utf-8")
    conventional = tmp_path / "requirements"
    conventional.mkdir()
    (conventional / "test.txt").write_text("# conventional\n", encoding="utf-8")
    decoy = tmp_path / action_bootstrap.VENV_DIR
    decoy.mkdir()
    (decoy / "requirements.txt").write_text("# decoy\n", encoding="utf-8")

    install, skipped = action_bootstrap._discover_manifests(tmp_path)
    names = {str(path.relative_to(tmp_path)) for path in install}
    assert names == {
        "requirements.txt",
        "dev-requirements.txt",
        os.path.join("requirements", "test.txt"),
    }
    assert install[0].name == "requirements.txt"
    assert {str(path.relative_to(tmp_path)) for path in skipped} == {
        "requirements-model-server.txt",
        os.path.join("api-gateway", "requirements.txt"),
    }


def test_monorepos_without_root_manifests_use_service_manifests(tmp_path) -> None:
    """A monorepo of services with no root-level declaration falls back to
    the canonical names one directory down, still skipping variant lanes."""

    gateway = tmp_path / "api-gateway"
    gateway.mkdir()
    (gateway / "requirements.txt").write_text("# service\n", encoding="utf-8")
    worker = tmp_path / "worker"
    worker.mkdir()
    (worker / "requirements-gpu.txt").write_text("torch>=2\n", encoding="utf-8")

    install, skipped = action_bootstrap._discover_manifests(tmp_path)
    assert [str(path.relative_to(tmp_path)) for path in install] == [
        os.path.join("api-gateway", "requirements.txt")
    ]
    assert [str(path.relative_to(tmp_path)) for path in skipped] == [
        os.path.join("worker", "requirements-gpu.txt")
    ]


def test_optional_requirements_lanes_never_break_the_run(tmp_path, monkeypatch, capsys) -> None:
    """A heavyweight optional lane (a model server needing gigabyte-scale
    packages) is skipped with a plain explanation instead of failing the
    Action, exactly like every mainstream CI that installs named manifests."""

    (tmp_path / "requirements.txt").write_text("# nothing needed\n", encoding="utf-8")
    (tmp_path / "requirements-model-server.txt").write_text(
        "definitely-not-a-real-package-amosclaud-test\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    assert action_bootstrap.main() == 0
    output = capsys.readouterr().out
    assert "Skipping requirements-model-server.txt" in output
    assert "separate lanes" in output


def test_bespoke_layouts_fall_back_to_every_discovered_manifest(tmp_path) -> None:
    """A repository with only variant manifests still gets an environment."""

    (tmp_path / "requirements-ci.txt").write_text("# ci\n", encoding="utf-8")
    install, skipped = action_bootstrap._discover_manifests(tmp_path)
    assert [path.name for path in install] == ["requirements-ci.txt"]
    assert skipped == []


def test_deps_step_gets_a_larger_file_allowance(monkeypatch, tmp_path) -> None:
    """Installing declared dependencies writes real wheels, so the deps step
    passes a one-gigabyte per-file allowance through to the sandbox while the
    other fixed steps keep the strict default."""

    from amoscloud_ai import isolated_runner

    assert native_actions.DEPS_FILE_SIZE_LIMIT_BYTES == 1024**3
    assert isolated_runner._resolve_file_size_limit(None) == 128 * 1024**2
    assert (
        isolated_runner._resolve_file_size_limit(
            native_actions.DEPS_FILE_SIZE_LIMIT_BYTES
        )
        == 1024**3
    )
    # Absurd values are clamped to a sane range.
    assert isolated_runner._resolve_file_size_limit(1) == 16 * 1024**2
    assert isolated_runner._resolve_file_size_limit(10**18) == 4 * 1024**3

    captured: dict[str, object] = {}

    def _capture(command, **kwargs):
        captured.update(kwargs)
        return isolated_runner.IsolatedRunResult(returncode=0, output="", timed_out=False)

    monkeypatch.setattr(isolated_runner, "_run_in_process_sandbox", _capture)
    monkeypatch.setattr(isolated_runner.shutil, "which", lambda *_: None)
    monkeypatch.delenv("AMOSCLAUD_REQUIRE_CONTAINER", raising=False)
    isolated_runner.run_in_isolated_container(
        "python -m pytest -q",
        workspace=tmp_path,
        environment=SANDBOX_ENV,
        file_size_limit_bytes=native_actions.DEPS_FILE_SIZE_LIMIT_BYTES,
    )
    assert captured["file_size_limit_bytes"] == native_actions.DEPS_FILE_SIZE_LIMIT_BYTES


def test_plan_commands_stay_code_owned_and_parseable() -> None:
    """The plan still never executes repository-chosen commands, and each
    command parses under the fixed executable allowlist."""

    from amoscloud_ai.isolated_runner import parse_allowed_command

    assert [job_id for job_id, _, _ in native_actions.ACTION_PLAN] == [
        "compileall",
        "deps",
        "pytest",
    ]
    for _job_id, _name, command in native_actions.ACTION_PLAN:
        argv = parse_allowed_command(command, allowlist={"python", "python3"})
        assert Path(argv[0]).name in {"python", "python3"}

from pathlib import Path

import pytest

from amoscloud_ai.isolated_runner import (
    MAX_LOG_BYTES,
    RunnerConfigurationError,
    UnsafeCommandError,
    _BoundedByteBuffer,
    _parse_runner_user,
    parse_allowed_command,
    redact_output,
    run_in_isolated_container,
)


def test_allowed_command_is_returned_as_argument_vector() -> None:
    assert parse_allowed_command(
        "python -m pytest tests/test_server.py",
        {"python"},
    ) == ["python", "-m", "pytest", "tests/test_server.py"]


@pytest.mark.parametrize(
    "command",
    [
        "sh -c 'cat /etc/passwd'",
        "bash -lc 'echo unsafe'",
        "curl https://example.com",
        "python -m pytest\nrm -rf /",
    ],
)
def test_shells_unlisted_programs_and_control_characters_are_blocked(
    command: str,
) -> None:
    with pytest.raises(UnsafeCommandError):
        parse_allowed_command(command, {"python", "pytest"})


def test_secret_values_are_removed_from_persisted_output() -> None:
    output = redact_output(
        "token=super-secret-value and repeated super-secret-value",
        ["super-secret-value"],
    )

    assert "super-secret-value" not in output
    assert output.count("[REDACTED]") == 2


def test_live_output_buffer_is_bounded_before_process_completion() -> None:
    buffer = _BoundedByteBuffer(16)
    buffer.append(b"a" * 10)
    buffer.append(b"b" * 20)

    output = buffer.text()
    assert output.startswith("[output truncated]\n")
    assert output.endswith("b" * 16)
    assert len(output.encode("utf-8")) < MAX_LOG_BYTES


def test_runner_user_must_be_a_numeric_non_root_uid_and_gid() -> None:
    assert _parse_runner_user("1000:1001") == (1000, 1001)

    for value in ("root", "1000", "1000:staff", "0:0", "0:1000", "1000:0"):
        with pytest.raises(RunnerConfigurationError):
            _parse_runner_user(value)


def test_runner_source_prepares_root_created_workspace_without_following_symlinks() -> None:
    source = (
        Path(__file__).resolve().parents[1] / "amoscloud_ai" / "isolated_runner.py"
    ).read_text(encoding="utf-8")

    assert "def _prepare_workspace_ownership" in source
    assert "os.walk(root, followlinks=False)" in source
    assert "os.lchown" in source
    assert "_prepare_workspace_ownership(root, uid, gid)" in source
    assert "A root worker must configure AMOSCLAUD_RUNNER_USER" in source


def test_runner_source_never_invokes_a_host_shell() -> None:
    source = (
        Path(__file__).resolve().parents[1] / "amoscloud_ai" / "isolated_runner.py"
    ).read_text(encoding="utf-8")

    assert "shell=True" not in source
    assert '"--network",\n        "none"' in source
    assert '"--cap-drop",\n        "ALL"' in source
    assert '"no-new-privileges"' in source
    assert "subprocess.Popen" in source
    assert "_BoundedByteBuffer(MAX_LOG_BYTES)" in source
    assert 'return f"{uid}:{gid}", uid, gid' in source
    assert "65532:65532" not in source
    assert "--cidfile" in source


def test_process_sandbox_runs_when_container_station_is_missing(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("AMOSCLAUD_DOCKER_BINARY", "amosclaud-missing-docker-binary")
    monkeypatch.delenv("AMOSCLAUD_RUNNER_IMAGE", raising=False)
    monkeypatch.delenv("AMOSCLAUD_RUNNER_REQUIRE_CONTAINER", raising=False)
    (tmp_path / "ok.py").write_text("print('sandbox ok')\n", encoding="utf-8")

    result = run_in_isolated_container(
        "python ok.py",
        workspace=tmp_path,
        environment={"PYTHONDONTWRITEBYTECODE": "1"},
        timeout_seconds=60,
    )

    assert result.returncode == 0
    assert result.timed_out is False
    assert "sandbox ok" in result.output
    assert "process sandbox" in result.output.lower()


def test_process_sandbox_reports_failures_honestly(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("AMOSCLAUD_DOCKER_BINARY", "amosclaud-missing-docker-binary")
    monkeypatch.delenv("AMOSCLAUD_RUNNER_IMAGE", raising=False)
    monkeypatch.delenv("AMOSCLAUD_RUNNER_REQUIRE_CONTAINER", raising=False)
    (tmp_path / "bad.py").write_text("raise SystemExit(3)\n", encoding="utf-8")

    result = run_in_isolated_container(
        "python bad.py",
        workspace=tmp_path,
        environment={},
        timeout_seconds=60,
    )

    assert result.returncode == 3
    assert result.timed_out is False


def test_operator_can_require_container_isolation(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("AMOSCLAUD_DOCKER_BINARY", "amosclaud-missing-docker-binary")
    monkeypatch.delenv("AMOSCLAUD_RUNNER_IMAGE", raising=False)
    monkeypatch.setenv("AMOSCLAUD_RUNNER_REQUIRE_CONTAINER", "true")

    with pytest.raises(RunnerConfigurationError):
        run_in_isolated_container(
            "python ok.py",
            workspace=tmp_path,
            environment={},
        )

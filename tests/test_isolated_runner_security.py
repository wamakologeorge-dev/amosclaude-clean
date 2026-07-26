from pathlib import Path

import pytest

from amoscloud_ai.isolated_runner import (
    UnsafeCommandError,
    parse_allowed_command,
    redact_output,
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


def test_runner_source_never_invokes_a_host_shell() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "amoscloud_ai"
        / "isolated_runner.py"
    ).read_text(encoding="utf-8")

    assert "shell=True" not in source
    assert '"--network",\n        "none"' in source
    assert '"--cap-drop",\n        "ALL"' in source
    assert '"no-new-privileges"' in source

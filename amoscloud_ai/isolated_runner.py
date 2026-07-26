"""Isolated command execution for untrusted Amosclaud project workloads.

The API process must never execute user-controlled build or test commands. This
module is called only by a background worker and launches a pre-provisioned
container with strict resource and privilege limits. Commands are passed as an
argument vector; a host shell is never involved.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence


DEFAULT_ALLOWLIST = {
    "python",
    "python3",
    "pip",
    "pip3",
    "pytest",
    "node",
    "npm",
    "npx",
    "pnpm",
    "yarn",
    "make",
}
BLOCKED_EXECUTABLES = {
    "ash",
    "bash",
    "cmd",
    "dash",
    "env",
    "fish",
    "powershell",
    "pwsh",
    "sh",
    "sudo",
    "zsh",
}
MAX_COMMAND_LENGTH = 4096
MAX_ARGUMENTS = 128
MAX_LOG_BYTES = 2_000_000


class RunnerConfigurationError(RuntimeError):
    """Raised when the isolated runner is not safely configured."""


class UnsafeCommandError(ValueError):
    """Raised when a requested command violates the runner policy."""


@dataclass(frozen=True, slots=True)
class IsolatedRunResult:
    returncode: int
    output: str
    timed_out: bool = False


def configured_allowlist() -> set[str]:
    raw = os.getenv("AMOSCLAUD_RUNNER_ALLOWLIST", "").strip()
    if not raw:
        return set(DEFAULT_ALLOWLIST)
    return {item.strip() for item in raw.split(",") if item.strip()}


def parse_allowed_command(command: str, allowlist: set[str] | None = None) -> list[str]:
    """Parse one command without invoking a shell and enforce an executable allowlist."""

    if not isinstance(command, str):
        raise UnsafeCommandError("command must be text")
    if not command.strip():
        raise UnsafeCommandError("command is empty")
    if len(command) > MAX_COMMAND_LENGTH:
        raise UnsafeCommandError("command exceeds the maximum length")
    if "\x00" in command or "\n" in command or "\r" in command:
        raise UnsafeCommandError("command contains forbidden control characters")

    try:
        argv = shlex.split(command, posix=True)
    except ValueError as exc:
        raise UnsafeCommandError("command quoting is invalid") from exc
    if not argv:
        raise UnsafeCommandError("command is empty")
    if len(argv) > MAX_ARGUMENTS:
        raise UnsafeCommandError("command has too many arguments")

    executable = Path(argv[0]).name
    allowed = allowlist if allowlist is not None else configured_allowlist()
    if executable in BLOCKED_EXECUTABLES:
        raise UnsafeCommandError(f"shell executable is forbidden: {executable}")
    if executable not in allowed:
        raise UnsafeCommandError(f"executable is not allowlisted: {executable}")

    return argv


def redact_output(text: str, secret_values: Sequence[str]) -> str:
    """Remove known secret values before logs are persisted or returned."""

    redacted = text or ""
    for value in sorted({item for item in secret_values if item}, key=len, reverse=True):
        redacted = redacted.replace(value, "[REDACTED]")
    encoded = redacted.encode("utf-8", errors="replace")
    if len(encoded) > MAX_LOG_BYTES:
        encoded = encoded[-MAX_LOG_BYTES:]
        redacted = "[output truncated]\n" + encoded.decode("utf-8", errors="replace")
    return redacted


def _write_environment_file(directory: Path, environment: Mapping[str, str]) -> Path:
    """Write a short-lived Docker env file without putting secrets in command arguments."""

    directory.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        prefix="amosclaud-runner-",
        suffix=".env",
        dir=directory,
        delete=False,
    )
    try:
        for key, value in sorted(environment.items()):
            if not key.replace("_", "").isalnum() or not key or key[0].isdigit():
                continue
            safe_value = str(value).replace("\x00", "").replace("\r", "").replace("\n", "\\n")
            handle.write(f"{key}={safe_value}\n")
    finally:
        handle.close()
    path = Path(handle.name)
    path.chmod(0o600)
    return path


def run_in_isolated_container(
    command: str,
    *,
    workspace: Path,
    environment: Mapping[str, str],
    timeout_seconds: int | None = None,
) -> IsolatedRunResult:
    """Run an allowlisted command in a locked-down worker container."""

    docker = shutil.which(os.getenv("AMOSCLAUD_DOCKER_BINARY", "docker"))
    if not docker:
        raise RunnerConfigurationError("Docker is required on the isolated worker station")

    image = os.getenv("AMOSCLAUD_RUNNER_IMAGE", "").strip()
    if not image:
        raise RunnerConfigurationError("AMOSCLAUD_RUNNER_IMAGE is required")

    root = workspace.resolve()
    if not root.is_dir():
        raise RunnerConfigurationError("runner workspace does not exist")

    argv = parse_allowed_command(command)
    timeout = timeout_seconds or int(os.getenv("AMOSCLAUD_RUNNER_TIMEOUT_SECONDS", "600"))
    timeout = max(1, min(timeout, 3600))
    cpus = os.getenv("AMOSCLAUD_RUNNER_CPUS", "1.0")
    memory = os.getenv("AMOSCLAUD_RUNNER_MEMORY", "768m")
    pids = os.getenv("AMOSCLAUD_RUNNER_PIDS_LIMIT", "128")
    user = os.getenv("AMOSCLAUD_RUNNER_USER", "65532:65532")

    env_path = _write_environment_file(root, environment)
    docker_command = [
        docker,
        "run",
        "--rm",
        "--network",
        "none",
        "--cpus",
        cpus,
        "--memory",
        memory,
        "--pids-limit",
        pids,
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=64m",
        "--user",
        user,
        "--mount",
        f"type=bind,src={root},dst=/workspace",
        "--workdir",
        "/workspace",
        "--env-file",
        str(env_path),
        image,
        *argv,
    ]

    try:
        completed = subprocess.run(
            docker_command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
        output = redact_output(completed.stdout or "", list(environment.values()))
        return IsolatedRunResult(completed.returncode, output)
    except subprocess.TimeoutExpired as exc:
        captured = exc.stdout or ""
        if isinstance(captured, bytes):
            captured = captured.decode("utf-8", errors="replace")
        output = redact_output(str(captured), list(environment.values()))
        return IsolatedRunResult(124, output + "\nRunner timed out.\n", timed_out=True)
    finally:
        env_path.unlink(missing_ok=True)

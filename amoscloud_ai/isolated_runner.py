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
import threading
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Mapping, Sequence


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
READ_CHUNK_BYTES = 64 * 1024


class RunnerConfigurationError(RuntimeError):
    """Raised when the isolated runner is not safely configured."""


class UnsafeCommandError(ValueError):
    """Raised when a requested command violates the runner policy."""


@dataclass(frozen=True, slots=True)
class IsolatedRunResult:
    returncode: int
    output: str
    timed_out: bool = False


class _BoundedByteBuffer:
    """Thread-safe tail buffer that never retains more than its byte limit."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self._chunks: deque[bytes] = deque()
        self._size = 0
        self._truncated = False
        self._lock = threading.Lock()

    def append(self, chunk: bytes) -> None:
        if not chunk:
            return
        with self._lock:
            if len(chunk) >= self.limit:
                self._chunks.clear()
                self._chunks.append(chunk[-self.limit :])
                self._size = self.limit
                self._truncated = True
                return
            self._chunks.append(chunk)
            self._size += len(chunk)
            while self._size > self.limit and self._chunks:
                excess = self._size - self.limit
                first = self._chunks[0]
                if len(first) <= excess:
                    self._chunks.popleft()
                    self._size -= len(first)
                else:
                    self._chunks[0] = first[excess:]
                    self._size -= excess
                self._truncated = True

    def text(self) -> str:
        with self._lock:
            payload = b"".join(self._chunks)
            truncated = self._truncated
        decoded = payload.decode("utf-8", errors="replace")
        return ("[output truncated]\n" if truncated else "") + decoded


def _drain_output(stream: BinaryIO, buffer: _BoundedByteBuffer) -> None:
    try:
        while True:
            chunk = stream.read(READ_CHUNK_BYTES)
            if not chunk:
                return
            buffer.append(chunk)
    finally:
        stream.close()


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


def _write_environment_file(environment: Mapping[str, str]) -> Path:
    """Write a short-lived private env file outside the mounted workspace."""

    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        prefix="amosclaud-runner-",
        suffix=".env",
        delete=False,
    )
    try:
        for key, value in sorted(environment.items()):
            if not key.replace("_", "").isalnum() or not key or key[0].isdigit():
                continue
            safe_value = (
                str(value)
                .replace("\x00", "")
                .replace("\r", "")
                .replace("\n", "\\n")
            )
            handle.write(f"{key}={safe_value}\n")
    finally:
        handle.close()
    path = Path(handle.name)
    path.chmod(0o600)
    return path


def _parse_runner_user(value: str) -> tuple[int, int]:
    parts = value.split(":", 1)
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        raise RunnerConfigurationError(
            "AMOSCLAUD_RUNNER_USER must be a numeric non-root UID:GID"
        )
    uid, gid = (int(part) for part in parts)
    if uid <= 0 or gid <= 0:
        raise RunnerConfigurationError(
            "AMOSCLAUD_RUNNER_USER must be a numeric non-root UID:GID"
        )
    return uid, gid


def _runner_identity() -> tuple[str, int, int]:
    if not hasattr(os, "getuid") or not hasattr(os, "getgid"):
        raise RunnerConfigurationError("AMOSCLAUD_RUNNER_USER is required on this worker")

    current_uid = os.getuid()
    current_gid = os.getgid()
    configured = os.getenv("AMOSCLAUD_RUNNER_USER", "").strip()
    if configured:
        uid, gid = _parse_runner_user(configured)
        if current_uid != 0 and (uid != current_uid or gid != current_gid):
            raise RunnerConfigurationError(
                "A non-root worker may only use its own UID:GID for the runner"
            )
        return f"{uid}:{gid}", uid, gid

    if current_uid == 0:
        raise RunnerConfigurationError(
            "A root worker must configure AMOSCLAUD_RUNNER_USER to a non-root UID:GID"
        )
    return f"{current_uid}:{current_gid}", current_uid, current_gid


def _runner_user() -> str:
    """Return the Docker user string while retaining the legacy helper API."""

    user, _, _ = _runner_identity()
    return user


def _lchown(path: Path, uid: int, gid: int) -> None:
    try:
        if hasattr(os, "lchown"):
            os.lchown(path, uid, gid)
        else:
            os.chown(path, uid, gid, follow_symlinks=False)
    except FileNotFoundError:
        return


def _prepare_workspace_ownership(root: Path, uid: int, gid: int) -> None:
    """Make a root-created workspace writable by the configured non-root container.

    The traversal never follows symlinks. Non-root workers already run containers
    with their own UID:GID and therefore require no ownership mutation.
    """

    if not hasattr(os, "getuid") or os.getuid() != 0:
        return
    _lchown(root, uid, gid)
    for directory, directory_names, file_names in os.walk(root, followlinks=False):
        base = Path(directory)
        for name in directory_names:
            _lchown(base / name, uid, gid)
        for name in file_names:
            _lchown(base / name, uid, gid)


def _terminate_container(docker: str, cid_path: Path, process: subprocess.Popen[bytes]) -> None:
    container_id = ""
    if cid_path.is_file():
        container_id = cid_path.read_text(encoding="utf-8", errors="ignore").strip()
    if container_id:
        subprocess.run(
            [docker, "kill", container_id],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
            check=False,
        )
    if process.poll() is None:
        process.kill()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        pass


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
    if not os.access(root, os.W_OK | os.X_OK):
        raise RunnerConfigurationError("runner workspace is not writable by the worker")

    argv = parse_allowed_command(command)
    timeout = timeout_seconds or int(os.getenv("AMOSCLAUD_RUNNER_TIMEOUT_SECONDS", "600"))
    timeout = max(1, min(timeout, 3600))
    cpus = os.getenv("AMOSCLAUD_RUNNER_CPUS", "1.0")
    memory = os.getenv("AMOSCLAUD_RUNNER_MEMORY", "768m")
    pids = os.getenv("AMOSCLAUD_RUNNER_PIDS_LIMIT", "128")
    user, uid, gid = _runner_identity()
    _prepare_workspace_ownership(root, uid, gid)

    env_path = _write_environment_file(environment)
    cid_handle = tempfile.NamedTemporaryFile(
        prefix="amosclaud-runner-", suffix=".cid", delete=False
    )
    cid_handle.close()
    cid_path = Path(cid_handle.name)
    cid_path.unlink(missing_ok=True)

    docker_command = [
        docker,
        "run",
        "--rm",
        "--cidfile",
        str(cid_path),
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
        "--env",
        "HOME=/tmp",
        image,
        *argv,
    ]

    buffer = _BoundedByteBuffer(MAX_LOG_BYTES)
    timed_out = False
    process: subprocess.Popen[bytes] | None = None
    reader: threading.Thread | None = None
    try:
        process = subprocess.Popen(
            docker_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if process.stdout is None:
            raise RunnerConfigurationError("isolated runner did not expose an output stream")
        reader = threading.Thread(
            target=_drain_output,
            args=(process.stdout, buffer),
            daemon=True,
        )
        reader.start()
        try:
            returncode = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            _terminate_container(docker, cid_path, process)
            returncode = 124
        reader.join(timeout=15)
        output = redact_output(buffer.text(), list(environment.values()))
        if timed_out:
            output += "\nRunner timed out.\n"
        return IsolatedRunResult(returncode, output, timed_out=timed_out)
    finally:
        if process is not None and process.poll() is None:
            _terminate_container(docker, cid_path, process)
        if reader is not None and reader.is_alive():
            reader.join(timeout=1)
        env_path.unlink(missing_ok=True)
        cid_path.unlink(missing_ok=True)

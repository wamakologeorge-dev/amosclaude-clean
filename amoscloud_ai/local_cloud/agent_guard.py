"""Bounded local AI repair loop for tests and Docker builds.

The backend owns the command. The local model may return only a unified diff;
it cannot choose a command, edit secrets/state, or escape the workspace.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Mapping, Protocol, Sequence


class AgentGuardError(RuntimeError):
    """Raised when a guarded repair cannot continue safely."""


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str

    @property
    def output(self) -> str:
        return (self.stdout + "\n" + self.stderr).strip()


@dataclass(frozen=True)
class BuildFailureContext:
    attempt: int
    maximum_attempts: int
    label: str
    command: tuple[str, ...]
    output: str
    source_context: str


@dataclass(frozen=True)
class GuardAttempt:
    attempt: int
    returncode: int
    patch_applied: bool
    output: str
    changed_files: tuple[str, ...] = ()


@dataclass(frozen=True)
class GuardResult:
    status: str
    label: str
    attempts: tuple[GuardAttempt, ...]
    changed_files: tuple[str, ...]
    rolled_back: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "label": self.label,
            "attempts": [asdict(item) for item in self.attempts],
            "changed_files": list(self.changed_files),
            "rolled_back": self.rolled_back,
        }


class PatchModel(Protocol):
    def propose_patch(self, context: BuildFailureContext) -> str: ...


Runner = Callable[[Sequence[str], Path, Mapping[str, str], int], CommandResult]
_PROTECTED_PARTS = {
    ".git",
    ".hg",
    ".svn",
    ".amosclaud",
    "amosclaud_vault",
    ".venv",
    "venv",
    "node_modules",
}
_PROTECTED_NAMES = {
    ".env",
    ".env.local",
    ".env.production",
    "authority.json",
    "runtime.db",
    "vault.db",
}
_PROTECTED_SUFFIXES = {
    ".pem",
    ".key",
    ".p12",
    ".pfx",
    ".db",
    ".sqlite",
    ".sqlite3",
}
_HEADER = re.compile(r"^(?:---|\+\+\+)\s+([^\t\n]+)", re.MULTILINE)
_TRACE_PATHS = (
    re.compile(r'File\s+"(?P<path>[^"\n]+)",\s+line\s+\d+'),
    re.compile(
        r"(?m)^(?P<path>[^\s:\n][^:\n]*\.(?:py|js|ts|tsx|jsx|go|rs|java))"
        r":\d+(?::\d+)?"
    ),
)


def _run(
    command: Sequence[str],
    cwd: Path,
    env: Mapping[str, str],
    timeout: int,
) -> CommandResult:
    completed = subprocess.run(
        list(command),
        cwd=cwd,
        env=dict(env),
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


class LocalHTTPPatchModel:
    """OpenAI-compatible adapter intended for a loopback local model server."""

    def __init__(self, endpoint: str, model: str, *, timeout: int = 120) -> None:
        parsed = urllib.parse.urlparse(endpoint)
        allow_remote = os.getenv("AMOSCLAUD_LOCAL_MODEL_ALLOW_REMOTE", "false").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise AgentGuardError("AMOSCLAUD_LOCAL_MODEL_URL must be an HTTP(S) URL")
        if not allow_remote and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise AgentGuardError(
                "Local model endpoint must use loopback unless explicitly allowed"
            )
        self.endpoint = endpoint
        self.model = model
        self.timeout = timeout

    def propose_patch(self, context: BuildFailureContext) -> str:
        prompt = (
            "Return ONLY a unified diff that repairs this verified local failure. "
            "Do not return markdown, prose, commands, secrets, new files, deleted files, "
            "renames, or edits to .git, amosclaud_vault, .env, databases, keys, or "
            "certificates.\n\n"
            f"Operation: {context.label}\n"
            f"Attempt: {context.attempt}/{context.maximum_attempts}\n"
            f"Fixed command: {list(context.command)!r}\n"
            f"Failure output:\n{context.output}\n\n"
            f"Relevant source:\n{context.source_context}"
        )
        body = json.dumps(
            {
                "model": self.model,
                "temperature": 0,
                "messages": [
                    {"role": "system", "content": "Return one safe unified diff only."},
                    {"role": "user", "content": prompt},
                ],
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            self.endpoint,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
            return str(payload["choices"][0]["message"]["content"])
        except (OSError, ValueError, KeyError, IndexError, TypeError) as exc:
            raise AgentGuardError("Local model request or response failed") from exc


def model_from_environment() -> PatchModel:
    endpoint = os.getenv("AMOSCLAUD_LOCAL_MODEL_URL", "").strip()
    model = os.getenv("AMOSCLAUD_LOCAL_MODEL_NAME", "").strip()
    if not endpoint or not model:
        raise AgentGuardError(
            "Set AMOSCLAUD_LOCAL_MODEL_URL and AMOSCLAUD_LOCAL_MODEL_NAME"
        )
    return LocalHTTPPatchModel(endpoint, model)


class AgentBuildGuard:
    """Run, repair, and re-run one backend-owned command up to three attempts."""

    def __init__(
        self,
        workspace: Path,
        model: PatchModel,
        *,
        maximum_attempts: int = 3,
        runner: Runner | None = None,
    ) -> None:
        self.workspace = Path(workspace).expanduser().resolve(strict=True)
        if not self.workspace.is_dir():
            raise AgentGuardError("Workspace must be an existing directory")
        if maximum_attempts < 1 or maximum_attempts > 3:
            raise AgentGuardError("maximum_attempts must be between 1 and 3")
        if not shutil.which("git"):
            raise AgentGuardError("git is required to validate and apply model patches")
        self.model = model
        self.maximum_attempts = maximum_attempts
        self.runner = runner or _run

    def run(
        self,
        command: Sequence[str],
        *,
        label: str,
        timeout: int,
        env: Mapping[str, str] | None = None,
    ) -> GuardResult:
        if not command or not all(isinstance(item, str) and item for item in command):
            raise AgentGuardError("Command must be a fixed non-empty argument list")
        execution_env = {
            **os.environ,
            **dict(env or {}),
            "CI": "1",
            "PYTHONUNBUFFERED": "1",
        }
        backups: dict[Path, bytes] = {}
        changed: set[str] = set()
        attempts: list[GuardAttempt] = []
        try:
            for attempt in range(1, self.maximum_attempts + 1):
                result = self.runner(tuple(command), self.workspace, execution_env, timeout)
                output = result.output[-30_000:]
                if result.returncode == 0:
                    attempts.append(GuardAttempt(attempt, 0, False, output))
                    return GuardResult(
                        "succeeded",
                        label,
                        tuple(attempts),
                        tuple(sorted(changed)),
                        False,
                    )
                if attempt == self.maximum_attempts:
                    attempts.append(
                        GuardAttempt(attempt, result.returncode, False, output)
                    )
                    break
                context = BuildFailureContext(
                    attempt,
                    self.maximum_attempts,
                    label,
                    tuple(command),
                    output,
                    self._source_context(output),
                )
                touched = self._apply_patch(self.model.propose_patch(context), backups)
                changed.update(touched)
                attempts.append(
                    GuardAttempt(
                        attempt,
                        result.returncode,
                        True,
                        output,
                        tuple(sorted(touched)),
                    )
                )
        except Exception:
            self._restore(backups)
            raise
        self._restore(backups)
        return GuardResult(
            "failed",
            label,
            tuple(attempts),
            tuple(sorted(changed)),
            bool(backups),
        )

    def _safe_file(self, value: str) -> Path:
        cleaned = value.strip()
        if cleaned.startswith(("a/", "b/")):
            cleaned = cleaned[2:]
        relative = Path(cleaned)
        if (
            not cleaned
            or cleaned == "/dev/null"
            or "\x00" in cleaned
            or relative.is_absolute()
            or ".." in relative.parts
        ):
            raise AgentGuardError("Patch path must be a relative existing file")

        lexical = self.workspace / relative
        cursor = self.workspace
        for part in relative.parts:
            cursor = cursor / part
            if cursor.is_symlink():
                raise AgentGuardError("Patch target cannot traverse a symlink")

        try:
            candidate = lexical.resolve(strict=True)
            checked_relative = candidate.relative_to(self.workspace)
        except (OSError, ValueError) as exc:
            raise AgentGuardError("Patch path escapes the workspace") from exc
        if not candidate.is_file():
            raise AgentGuardError("Patch target must be an existing regular file")
        if any(part in _PROTECTED_PARTS for part in checked_relative.parts):
            raise AgentGuardError("Patch targets a protected workspace path")
        if candidate.name in _PROTECTED_NAMES:
            raise AgentGuardError("Patch targets protected secret material")
        if candidate.suffix.lower() in _PROTECTED_SUFFIXES:
            raise AgentGuardError("Patch targets protected state material")
        if candidate.stat().st_size > 1_000_000:
            raise AgentGuardError("Patch target is too large")
        return candidate

    def _validate_patch(self, patch: str) -> tuple[Path, ...]:
        text = str(patch or "").strip()
        if not text or "```" in text or len(text.encode("utf-8")) > 200_000:
            raise AgentGuardError("Model must return one bounded unified diff")
        headers = _HEADER.findall(text)
        if not headers or len(headers) % 2 or len(headers) > 16:
            raise AgentGuardError("Unified diff headers are invalid")
        targets: list[Path] = []
        for index in range(0, len(headers), 2):
            old = headers[index]
            new = headers[index + 1]
            old_name = old[2:] if old.startswith("a/") else old
            new_name = new[2:] if new.startswith("b/") else new
            if old_name != new_name or old_name == "/dev/null":
                raise AgentGuardError("Repair cannot create, delete, or rename files")
            target = self._safe_file(new_name)
            if target not in targets:
                targets.append(target)
        return tuple(targets)

    def _apply_patch(self, patch: str, backups: dict[Path, bytes]) -> set[str]:
        targets = self._validate_patch(patch)
        for target in targets:
            backups.setdefault(target, target.read_bytes())
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".diff") as handle:
            handle.write(patch)
            handle.flush()
            checked = subprocess.run(
                ["git", "apply", "--check", "--whitespace=error-all", handle.name],
                cwd=self.workspace,
                capture_output=True,
                text=True,
                check=False,
            )
            if checked.returncode != 0:
                raise AgentGuardError(
                    f"Model patch was rejected: {checked.stderr[-1000:]}"
                )
            applied = subprocess.run(
                ["git", "apply", "--whitespace=nowarn", handle.name],
                cwd=self.workspace,
                capture_output=True,
                text=True,
                check=False,
            )
            if applied.returncode != 0:
                raise AgentGuardError(
                    f"Model patch could not be applied: {applied.stderr[-1000:]}"
                )
        return {path.relative_to(self.workspace).as_posix() for path in targets}

    @staticmethod
    def _restore(backups: Mapping[Path, bytes]) -> None:
        for path, content in backups.items():
            path.write_bytes(content)

    def _source_context(self, output: str) -> str:
        candidates: list[Path] = []
        for pattern in _TRACE_PATHS:
            for match in pattern.finditer(output):
                raw = Path(match.group("path"))
                try:
                    relative = raw.relative_to(self.workspace) if raw.is_absolute() else raw
                    safe = self._safe_file(str(relative))
                except (AgentGuardError, ValueError, OSError):
                    continue
                if safe not in candidates:
                    candidates.append(safe)
                if len(candidates) == 4:
                    break
        sections: list[str] = []
        for path in candidates:
            try:
                content = path.read_text(encoding="utf-8")[:20_000]
            except (OSError, UnicodeDecodeError):
                continue
            sections.append(
                f"--- {path.relative_to(self.workspace).as_posix()} ---\n{content}"
            )
        return "\n\n".join(sections) or "No safe source file was identified."

#!/usr/bin/env python3
"""Generate, apply, and verify a constrained repair patch for CI failures.

The fixer uses the Amosclaud-owned model gateway, never edits protected automation
or secret-bearing files, never commits an unverified patch, and emits a
machine-readable report for the workflow.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOG_PATH = ROOT / os.getenv("AMOSCLAUD_FAILURE_LOG", "amosclaud-failure.log")
REPORT_PATH = ROOT / "amosclaud-fixer-report.json"
AMOSCLAUD_API_URL = os.getenv("AMOSCLAUD_API_URL", "http://www.amosclaud.com/").rstrip("/")
AMOSCLAUD_API_KEY = os.getenv("AMOSCLAUD_API_KEY", "").strip()
MODEL = os.getenv("AMOSCLAUD_FIXER_MODEL", "amosclaud-agent")
MAX_ATTEMPTS = max(1, min(int(os.getenv("AMOSCLAUD_FIXER_ATTEMPTS", "3")), 3))
MAX_PATCH_BYTES = 250_000
MAX_CHANGED_FILES = 25
PROTECTED_PREFIXES = (
    ".git/",
    ".github/workflows/",
    ".github/actions/",
)
PROTECTED_NAMES = {
    ".env",
    ".env.local",
    ".env.production",
    "secrets.json",
    "credentials.json",
}
VERIFY_COMMANDS = [
    [sys.executable, "-m", "compileall", "-q", "amoscloud_ai", "src", "tests"],
    [sys.executable, "-m", "pytest", "-q", "--disable-warnings", "--maxfail=25"],
]


def run(command: list[str], *, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=check,
    )


def git(*args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    return run(["git", *args], check=check)


def redact(text: str) -> str:
    patterns = (
        r"(?i)(api[_-]?key|token|secret|password)\s*[:=]\s*[^\s]+",
        r"gh[pousr]_[A-Za-z0-9_]{20,}",
        r"amos_(?:svc|agent|auto)_[A-Za-z0-9_-]{16,}",
        r"sk-[A-Za-z0-9_-]{16,}",
    )
    for pattern in patterns:
        text = re.sub(pattern, r"\1=[REDACTED]", text)
    return text[-60_000:]


def repository_context() -> str:
    files = git("ls-files").stdout.splitlines()
    important = [
        path
        for path in files
        if path.endswith((".py", ".js", ".ts", ".html", ".yml", ".yaml", ".toml", ".json"))
        and not path.startswith(("node_modules/", "dist/", "build/", ".venv/"))
    ][:500]
    status = git("status", "--short").stdout
    return "Tracked files:\n" + "\n".join(important) + "\n\nGit status:\n" + status


def extract_diff(response_text: str) -> str:
    match = re.search(r"```(?:diff|patch)?\s*(.*?)```", response_text, re.DOTALL)
    candidate = match.group(1) if match else response_text
    start = candidate.find("diff --git ")
    if start < 0:
        raise ValueError("Amosclaud response did not contain a unified git diff")
    return candidate[start:].strip() + "\n"


def changed_paths(patch: str) -> list[str]:
    return re.findall(r"^\+\+\+ b/(.+)$", patch, re.MULTILINE)


def validate_patch(patch: str) -> list[str]:
    if len(patch.encode("utf-8")) > MAX_PATCH_BYTES:
        raise ValueError("generated patch exceeds size limit")
    paths = changed_paths(patch)
    if not paths:
        raise ValueError("generated patch has no changed files")
    if len(set(paths)) > MAX_CHANGED_FILES:
        raise ValueError("generated patch changes too many files")
    for path in paths:
        normalized = path.lstrip("./")
        if normalized in PROTECTED_NAMES or normalized.startswith(PROTECTED_PREFIXES):
            raise ValueError(f"generated patch targets protected path: {normalized}")
        if ".." in Path(normalized).parts:
            raise ValueError(f"generated patch contains unsafe path: {normalized}")
    return sorted(set(paths))


def verify() -> tuple[bool, str]:
    output: list[str] = []
    for command in VERIFY_COMMANDS:
        result = run(command)
        output.append(f"$ {' '.join(command)}\n{result.stdout}")
        if result.returncode != 0:
            return False, redact("\n\n".join(output))
    return True, redact("\n\n".join(output))


def restore() -> None:
    git("reset", "--hard", "HEAD", check=True)
    git("clean", "-fd", "--exclude=amosclaud-failure.log", "--exclude=amosclaud-fixer-report.json")


def amosclaud_chat(instructions: str, prompt: str) -> str:
    """Call Amosclaud's compatible gateway with an Amosclaud-owned key."""
    payload = json.dumps(
        {
            "model": MODEL,
            "messages": [
                {"role": "system", "content": instructions},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{AMOSCLAUD_API_URL}/v1/chat/completions",
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {AMOSCLAUD_API_KEY}",
            "Content-Type": "application/json",
            "User-Agent": "Amosclaud-Fixer/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Amosclaud gateway returned HTTP {error.code}: {redact(detail)}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"Amosclaud gateway is unreachable: {error.reason}") from error

    try:
        content = result["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as error:
        raise RuntimeError("Amosclaud gateway returned an invalid completion payload") from error
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("Amosclaud gateway returned no repair content")
    return content


def request_patch(failure_log: str, previous_feedback: str) -> str:
    instructions = """You are Amosclaud AI Fixer operating inside a Git repository.
Return ONLY one unified git diff inside a ```diff fence.
Repair the root cause shown by the failure evidence. Prefer the smallest correct change.
Do not edit GitHub workflows, actions, secrets, environment files, generated files, or dependency lock files.
Do not delete tests merely to make CI green. Update stale tests only when repository behavior is clearly intentional.
Preserve public APIs unless the failure proves they are broken. Add or improve tests when useful.
The patch must apply with `git apply` and must not contain commentary outside the diff.
"""
    prompt = (
        f"Failure evidence:\n{failure_log}\n\n"
        f"Repository context:\n{repository_context()}\n\n"
        f"Previous repair feedback:\n{previous_feedback or 'none'}"
    )
    return extract_diff(amosclaud_chat(instructions, prompt))


def main() -> int:
    if not AMOSCLAUD_API_KEY:
        raise SystemExit("AMOSCLAUD_API_KEY is required for Amosclaud AI Fixer")
    failure_log = redact(LOG_PATH.read_text(encoding="utf-8", errors="replace") if LOG_PATH.exists() else "")
    if not failure_log.strip():
        failure_log = "CI failed without an attached log. Reproduce and repair failures using the repository test suite."

    attempts: list[dict[str, object]] = []
    feedback = ""

    for attempt in range(1, MAX_ATTEMPTS + 1):
        restore()
        try:
            patch = request_patch(failure_log, feedback)
            paths = validate_patch(patch)
            patch_path = ROOT / f"amosclaud-fix-attempt-{attempt}.patch"
            patch_path.write_text(patch, encoding="utf-8")
            check = git("apply", "--check", str(patch_path))
            if check.returncode != 0:
                raise ValueError(f"git apply --check failed:\n{check.stdout}")
            git("apply", "--whitespace=fix", str(patch_path), check=True)
            passed, verification = verify()
            attempts.append({"attempt": attempt, "paths": paths, "verified": passed, "verification": verification})
            if passed:
                REPORT_PATH.write_text(
                    json.dumps(
                        {
                            "status": "verified",
                            "provider": "amosclaud",
                            "model": MODEL,
                            "attempts": attempts,
                            "changed_files": paths,
                        },
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                print("AMOSCLAUD_FIX_VERIFIED=true")
                print("AMOSCLAUD_CHANGED_FILES=" + ",".join(paths))
                return 0
            feedback = verification
        except Exception as error:
            feedback = redact(f"{type(error).__name__}: {error}")
            attempts.append({"attempt": attempt, "verified": False, "error": feedback})

    restore()
    REPORT_PATH.write_text(
        json.dumps(
            {"status": "failed", "provider": "amosclaud", "model": MODEL, "attempts": attempts},
            indent=2,
        ),
        encoding="utf-8",
    )
    print("AMOSCLAUD_FIX_VERIFIED=false")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

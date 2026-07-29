#!/usr/bin/env python3
"""Create a verified Amosclaud change proposal on a review branch.

The daily agent asks the Amosclaud-owned model gateway for one bounded unified
diff, validates the patch, runs repository verification, and publishes a pull
request. It never writes directly to the default branch and never force-pushes.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
API_URL = os.getenv("AMOSCLAUD_API_URL", "https://www.amosclaud.com").rstrip("/")
API_KEY = os.getenv("AMOSCLAUD_API_KEY", "").strip()
MODEL = os.getenv("AMOSCLAUD_CRON_MODEL", "amosclaud-agent").strip()
GITHUB_REPOSITORY = os.getenv("GITHUB_REPOSITORY", "wamakologeorge-dev/amosclaude-clean").strip()
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()
DEFAULT_BRANCH = os.getenv("AMOSCLAUD_DEFAULT_BRANCH", "main").strip()
MAX_PATCH_BYTES = 250_000
MAX_CHANGED_FILES = 12
MAX_EVIDENCE_CHARS = 50_000

ALLOWED_PREFIXES = (
    "amoscloud_ai/",
    "src/",
    "web/",
    "api/",
    "app/",
    "tests/",
    "docs/",
)
RUNTIME_PREFIXES = ("amoscloud_ai/", "src/", "web/", "api/", "app/")
PROTECTED_PREFIXES = (
    ".git/",
    ".github/",
    ".amosclaud/",
    "Infrastructure/",
    "infrastructure/",
)
PROTECTED_EXACT = {
    "AGENTS.md",
    "SECURITY.md",
    "CODEOWNERS",
    "Dockerfile",
    "railway.json",
    "vercel.json",
}
FORBIDDEN_PATCH_MARKERS = (
    "GIT binary patch",
    "new file mode 120000",
    "new file mode 160000",
    "old mode 120000",
    "old mode 160000",
)


class CronAgentError(RuntimeError):
    """Raised when the daily proposal cannot be produced safely."""


def log(message: str, level: str = "INFO") -> None:
    timestamp = datetime.now(UTC).isoformat(timespec="seconds")
    print(f"[{timestamp}] [{level}] {message}", flush=True)


def run(command: list[str], *, check: bool = False) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if check and result.returncode != 0:
        raise CronAgentError(
            f"Command failed ({result.returncode}): {' '.join(command)}\n"
            f"{redact(result.stdout)}"
        )
    return result


def redact(text: str) -> str:
    patterns = (
        r"gh[pousr]_[A-Za-z0-9_]{20,}",
        r"amos_(?:svc|agent|auto)_[A-Za-z0-9_-]{16,}",
        r"sk-[A-Za-z0-9_-]{16,}",
    )
    for pattern in patterns:
        text = re.sub(pattern, "[REDACTED]", text)
    text = re.sub(
        r"(?i)\b(api[_-]?key|token|secret|password)\s*[:=]\s*[^\s]+",
        lambda match: f"{match.group(1)}=[REDACTED]",
        text,
    )
    if len(text) <= MAX_EVIDENCE_CHARS:
        return text
    half = MAX_EVIDENCE_CHARS // 2
    return text[:half] + "\n...[truncated]...\n" + text[-half:]


def read_repository_instructions() -> str:
    sections: list[str] = []
    for relative in ("AGENTS.md", "README.md"):
        path = ROOT / relative
        if path.is_file():
            content = path.read_text(encoding="utf-8", errors="replace")
            sections.append(f"=== {relative} ===\n{content[:25_000]}")
    if not sections:
        raise CronAgentError("AGENTS.md and README.md are both unavailable")
    return "\n\n".join(sections)


def repository_context() -> str:
    tracked = run(["git", "ls-files"], check=True).stdout.splitlines()
    relevant = [
        path
        for path in tracked
        if path.startswith(ALLOWED_PREFIXES)
        and path.endswith((".py", ".js", ".ts", ".html", ".css", ".json", ".md"))
    ][:600]
    recent = run(["git", "log", "-8", "--pretty=format:%h %s"], check=True).stdout
    return "Tracked change targets:\n" + "\n".join(relevant) + ("\n\nRecent commits:\n" + recent)


def request_json(url: str, payload: dict[str, Any], token: str) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": "Amosclaud-Cron-Agent/1.0",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise CronAgentError(f"GitHub API returned HTTP {error.code}: {redact(detail)}") from error
    except urllib.error.URLError as error:
        raise CronAgentError(f"GitHub API is unreachable: {error.reason}") from error


def call_amosclaud(prompt: str) -> str:
    if not API_KEY:
        raise CronAgentError("AMOSCLAUD_API_KEY is not configured")
    payload = {
        "model": MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are Amosclaud's scheduled repository engineer. "
                    "Return exactly one unified git diff inside a diff code "
                    "fence. Make one small, useful, backward-compatible change "
                    "to an existing runtime component and update or add tests. "
                    "Do not modify workflows, agent policy, secrets, environment "
                    "files, infrastructure, dependency files, or instructions. "
                    "Do not create an unused top-level module."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "stream": False,
    }
    request = urllib.request.Request(
        f"{API_URL}/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
            "User-Agent": "Amosclaud-Cron-Agent/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise CronAgentError(
            f"Amosclaud gateway returned HTTP {error.code}: {redact(detail)}"
        ) from error
    except urllib.error.URLError as error:
        raise CronAgentError(f"Amosclaud gateway is unreachable: {error.reason}") from error

    try:
        content = result["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as error:
        raise CronAgentError("Amosclaud gateway returned an invalid completion payload") from error
    if not isinstance(content, str) or not content.strip():
        raise CronAgentError("Amosclaud gateway returned no proposal")
    return content


def extract_diff(response_text: str) -> str:
    fenced = re.search(r"```(?:diff|patch)?\s*(.*?)```", response_text, re.DOTALL)
    candidate = fenced.group(1) if fenced else response_text
    start = candidate.find("diff --git ")
    if start < 0:
        raise CronAgentError("Amosclaud response did not contain a unified git diff")
    return candidate[start:].strip() + "\n"


def patch_paths(patch: str) -> list[str]:
    paths: set[str] = set()
    for line in patch.splitlines():
        if not line.startswith("diff --git "):
            continue
        try:
            parts = shlex.split(line)
        except ValueError as error:
            raise CronAgentError("Generated patch has invalid quoting") from error
        if len(parts) != 4:
            raise CronAgentError("Generated patch has an invalid diff header")
        for item in parts[2:]:
            if item.startswith(("a/", "b/")):
                paths.add(item[2:])
    return sorted(paths)


def normalize_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def is_protected(path: str) -> bool:
    normalized = normalize_path(path)
    name = Path(normalized).name.lower()
    return (
        normalized in PROTECTED_EXACT
        or normalized.startswith(PROTECTED_PREFIXES)
        or name == ".env"
        or name.startswith(".env.")
        or name in {"secrets.json", "credentials.json"}
    )


def validate_patch(patch: str) -> list[str]:
    if len(patch.encode("utf-8")) > MAX_PATCH_BYTES:
        raise CronAgentError("Generated patch exceeds the size limit")
    for marker in FORBIDDEN_PATCH_MARKERS:
        if marker in patch:
            raise CronAgentError(f"Generated patch contains forbidden structure: {marker}")

    paths = patch_paths(patch)
    if not paths:
        raise CronAgentError("Generated patch has no changed files")
    if len(paths) > MAX_CHANGED_FILES:
        raise CronAgentError("Generated patch changes too many files")

    for path in paths:
        normalized = normalize_path(path)
        if (
            not normalized
            or Path(normalized).is_absolute()
            or ".." in Path(normalized).parts
            or "\x00" in normalized
        ):
            raise CronAgentError(f"Generated patch has unsafe path: {path}")
        if is_protected(normalized):
            raise CronAgentError(f"Generated patch targets protected path: {normalized}")
        if not normalized.startswith(ALLOWED_PREFIXES):
            raise CronAgentError(f"Generated patch targets an unsupported path: {normalized}")

    normalized_paths = [normalize_path(p) for p in paths]
    if not any(p.startswith(RUNTIME_PREFIXES) for p in normalized_paths):
        raise CronAgentError("Generated patch does not modify an existing runtime component")
    if not any(p.startswith("tests/") for p in normalized_paths):
        raise CronAgentError("Generated patch must include test coverage")
    return normalized_paths


def restore_workspace() -> None:
    run(["git", "reset", "--hard", "HEAD"], check=True)
    run(["git", "clean", "-fd"], check=True)


def apply_and_verify(patch: str) -> list[str]:
    paths = validate_patch(patch)
    patch_file = ROOT / "amosclaud-cron-proposal.patch"
    patch_file.write_text(patch, encoding="utf-8")
    try:
        run(["git", "apply", "--check", str(patch_file)], check=True)
        run(
            ["git", "apply", "--whitespace=fix", str(patch_file)],
            check=True,
        )
    finally:
        patch_file.unlink(missing_ok=True)

    checks = (
        ["git", "diff", "--check"],
        [
            sys.executable,
            "-m",
            "compileall",
            "-q",
            "amoscloud_ai",
            "src",
            "tests",
        ],
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "--disable-warnings",
            "--maxfail=1",
        ],
    )
    for command in checks:
        result = run(command)
        log(f"Verification command: {' '.join(command)}")
        if result.stdout:
            print(redact(result.stdout), flush=True)
        if result.returncode != 0:
            raise CronAgentError(f"Verification failed: {' '.join(command)}")
    return paths


def create_issue(title: str, body: str) -> None:
    if not GITHUB_TOKEN:
        log("GITHUB_TOKEN is unavailable; issue report was not created", "WARNING")
        return
    request_json(
        f"https://api.github.com/repos/{GITHUB_REPOSITORY}/issues",
        {"title": title, "body": body},
        GITHUB_TOKEN,
    )


def publish_pull_request(paths: list[str]) -> str:
    if not GITHUB_TOKEN:
        raise CronAgentError("GITHUB_TOKEN is required to publish a proposal")
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    branch = f"amosclaud-cron/{stamp}"

    run(["git", "config", "user.name", "Amosclaud Cron Agent"], check=True)
    run(
        ["git", "config", "user.email", "cron-agent@amosclaud.internal"],
        check=True,
    )
    run(["git", "checkout", "-b", branch], check=True)
    run(["git", "add", "--", *paths], check=True)
    if run(["git", "diff", "--cached", "--quiet"]).returncode == 0:
        raise CronAgentError("Verified proposal produced no staged changes")
    run(
        [
            "git",
            "commit",
            "-m",
            "feat: add verified Amosclaud daily proposal",
        ],
        check=True,
    )
    run(["git", "push", "--set-upstream", "origin", branch], check=True)

    result = request_json(
        f"https://api.github.com/repos/{GITHUB_REPOSITORY}/pulls",
        {
            "title": "feat: verified Amosclaud daily proposal",
            "head": branch,
            "base": DEFAULT_BRANCH,
            "body": (
                "## Amosclaud daily proposal\n\n"
                "This change was generated on an isolated branch and published "
                "only after `git diff --check`, Python compilation, and the full "
                "pytest suite passed.\n\n"
                "Changed files:\n"
                + "\n".join(f"- `{path}`" for path in paths)
                + "\n\nNormal review and required CI checks are still required."
            ),
        },
        GITHUB_TOKEN,
    )
    html_url = result.get("html_url")
    if not isinstance(html_url, str) or not html_url:
        raise CronAgentError("GitHub created a pull request without a URL")
    return html_url


def run_daily_cycle() -> int:
    restore_workspace()
    prompt = (
        f"Repository operating instructions:\n{read_repository_instructions()}\n\n"
        f"Repository context:\n{repository_context()}\n\n"
        "Create one small production-quality improvement. Modify an existing "
        "runtime component and include focused tests."
    )
    try:
        patch = extract_diff(call_amosclaud(prompt))
        paths = apply_and_verify(patch)
        pull_request_url = publish_pull_request(paths)
    except Exception as error:
        restore_workspace()
        message = redact(f"{type(error).__name__}: {error}")
        log(message, "ERROR")
        try:
            create_issue(
                "Amosclaud daily proposal failed",
                (
                    "The scheduled agent stopped without publishing code.\n\n"
                    f"Reason:\n```\n{message}\n```\n\n"
                    "No direct default-branch write or force-push was attempted."
                ),
            )
        except Exception as report_error:
            log(
                f"Failure report could not be created: {redact(str(report_error))}",
                "ERROR",
            )
        return 1
    log(f"Published verified pull request: {pull_request_url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_daily_cycle())

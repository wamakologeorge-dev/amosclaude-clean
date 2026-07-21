from __future__ import annotations

import fnmatch
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.amosclaud_os.kernel import get_autonomous_kernel

BOT_NAMES = ("@amosclaud", "@amosclaud-bot")
COMMANDS = {"help", "status", "inspect", "verify", "review", "fix"}
WRITE_ASSOCIATIONS = {"OWNER", "MEMBER", "COLLABORATOR"}


@dataclass(frozen=True)
class BotResponse:
    body: str
    should_comment: bool = True


def _infer_assistant_command(remainder: str) -> tuple[str, str]:
    """Interpret natural-language requests as autonomous assistant intents.

    The assistant keeps the existing command surface, but users no longer need
    to memorize it. Write-oriented verbs route to Fixer, verification language
    routes to verify, review language routes to review, and everything else is
    treated as an Autonomous inspection/planning request.
    """
    objective = " ".join((remainder or "").strip().split())
    lowered = objective.lower()

    write_hints = (
        "fix ",
        "repair ",
        "create ",
        "build ",
        "implement ",
        "add ",
        "update ",
        "change ",
        "modify ",
        "remove ",
        "delete ",
        "refactor ",
        "make ",
        "resolve ",
        "correct ",
    )
    verify_hints = ("verify ", "test ", "check whether", "confirm ", "validate ")
    review_hints = ("review ", "look over ", "audit ", "analyze this pr", "analyse this pr")

    if any(lowered.startswith(hint) for hint in write_hints):
        return "fix", objective
    if any(lowered.startswith(hint) for hint in verify_hints):
        return "verify", objective
    if any(lowered.startswith(hint) for hint in review_hints):
        return "review", objective
    return "inspect", objective


def parse_command(text: str) -> tuple[str | None, str]:
    normalized = " ".join((text or "").strip().split())
    lowered = normalized.lower()
    matched_name = next((name for name in BOT_NAMES if lowered.startswith(name)), None)
    if not matched_name:
        return None, ""
    remainder = normalized[len(matched_name) :].strip()
    if not remainder:
        return "help", ""
    command, _, objective = remainder.partition(" ")
    command = command.lower().strip()
    if command in COMMANDS:
        return command, objective.strip()
    return _infer_assistant_command(remainder)


def _summarize_result(result: dict[str, Any]) -> str:
    status = str(result.get("status") or "unknown")
    error = result.get("error")
    evidence = [str(item) for item in (result.get("evidence") or [])][:8]
    changed_files = [str(item) for item in (result.get("changed_files") or [])][:20]
    artifacts = [str(item) for item in (result.get("artifacts") or [])][:10]

    lines = [f"**Runtime status:** `{status}`"]
    if error:
        lines.append(f"**Error:** `{error}`")
    if evidence:
        lines.append("\n**Evidence**\n" + "\n".join(f"- {item}" for item in evidence))
    if changed_files:
        lines.append("\n**Changed files**\n" + "\n".join(f"- `{item}`" for item in changed_files))
    if artifacts:
        lines.append("\n**Artifacts**\n" + "\n".join(f"- `{item}`" for item in artifacts))
    if not evidence and not changed_files and not artifacts:
        summary = result.get("summary") or result.get("message")
        if summary:
            lines.append(str(summary)[:3000])
    return "\n".join(lines)[:6000]


def _inspection_root(workspace: Path) -> tuple[Path, int | None]:
    root = workspace.resolve(strict=True)
    if not root.is_dir():
        raise RuntimeError("Amosclaud inspection workspace must be a directory")
    stat_result = root.stat()
    return root, getattr(stat_result, "st_uid", None)


def _safe_repository_file(root: Path, candidate: Path, owner_uid: int | None) -> Path | None:
    try:
        if candidate.is_symlink():
            return None
        resolved = candidate.resolve(strict=True)
        if not resolved.is_relative_to(root):
            return None
        stat_result = resolved.stat()
        if owner_uid is not None and getattr(stat_result, "st_uid", owner_uid) != owner_uid:
            return None
        if not resolved.is_file():
            return None
        return resolved
    except (FileNotFoundError, OSError, RuntimeError):
        return None


def _safe_relative_file(root: Path, relative: str, owner_uid: int | None) -> Path | None:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        return None
    return _safe_repository_file(root, root / path, owner_uid)


def _count_files(root: Path, patterns: tuple[str, ...], owner_uid: int | None) -> int:
    seen: set[Path] = set()
    for current, dirs, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        dirs[:] = [
            name
            for name in dirs
            if not (current_path / name).is_symlink()
            and (current_path / name).resolve(strict=False).is_relative_to(root)
        ]
        for name in files:
            if not any(fnmatch.fnmatch(name, pattern) for pattern in patterns):
                continue
            safe = _safe_repository_file(root, current_path / name, owner_uid)
            if safe is not None:
                seen.add(safe)
    return len(seen)


def _repository_inspection(workspace: Path) -> dict[str, Any]:
    root, owner_uid = _inspection_root(workspace)

    workflow_files: list[Path] = []
    workflows_dir = root / ".github" / "workflows"
    if workflows_dir.exists() and not workflows_dir.is_symlink():
        for pattern in ("*.yml", "*.yaml"):
            for candidate in workflows_dir.glob(pattern):
                safe = _safe_repository_file(root, candidate, owner_uid)
                if safe is not None:
                    workflow_files.append(safe)
    workflow_files = sorted(set(workflow_files))

    test_count = _count_files(root, ("test_*.py", "*_test.py"), owner_uid)
    has_pytest_config = any(
        _safe_relative_file(root, name, owner_uid) is not None
        for name in ("pyproject.toml", "pytest.ini", "tox.ini", "setup.cfg")
    )

    security_policy = any(
        _safe_relative_file(root, name, owner_uid) is not None
        for name in ("SECURITY.md", ".github/SECURITY.md")
    )
    dependabot = any(
        _safe_relative_file(root, name, owner_uid) is not None
        for name in (".github/dependabot.yml", ".github/dependabot.yaml")
    )

    pyproject = _safe_relative_file(root, "pyproject.toml", owner_uid)
    pyproject_text = pyproject.read_text(encoding="utf-8", errors="ignore") if pyproject else ""
    quality_tools = [
        tool
        for tool in ("ruff", "black", "mypy", "pytest", "coverage")
        if tool in pyproject_text.lower()
    ]

    findings = {
        "ci_cd": {
            "found": (
                f"{len(workflow_files)} GitHub Actions workflow file(s) are present."
                if workflow_files
                else "No GitHub Actions workflow files were found under `.github/workflows`."
            ),
            "recommendation": (
                "Keep required checks enabled and investigate any currently failing workflow before merging changes."
                if workflow_files
                else "Add a CI workflow that runs tests and verification on pull requests."
            ),
            "attention": "medium" if not workflow_files else "low",
        },
        "tests": {
            "found": f"{test_count} Python test file(s) were detected in the repository.",
            "recommendation": (
                "Keep the test suite running in CI and add coverage for every new bot/Fixer behavior."
                if test_count
                else "Add automated tests before expanding autonomous write behavior."
            ),
            "attention": "high" if not test_count else "low",
            "pytest_config": has_pytest_config,
        },
        "security": {
            "found": (
                f"Security policy: {'present' if security_policy else 'not detected'}; "
                f"Dependabot configuration: {'present' if dependabot else 'not detected'}."
            ),
            "recommendation": (
                "Keep dependency updates and repository write permissions reviewed, especially for autonomous fixes."
                if security_policy and dependabot
                else "Add the missing security policy and/or Dependabot configuration to strengthen repository maintenance."
            ),
            "attention": "low" if security_policy and dependabot else "medium",
        },
        "code_quality": {
            "found": (
                "Configured quality/test tooling detected in `pyproject.toml`: " + ", ".join(quality_tools) + "."
                if quality_tools
                else "No common Python quality tools were detected in `pyproject.toml`."
            ),
            "recommendation": (
                "Keep lint/type/test checks aligned with CI so Autonomous and Fixer changes are verified consistently."
                if quality_tools
                else "Configure linting and/or type checking so generated repairs receive an additional quality gate."
            ),
            "attention": "low" if quality_tools else "medium",
        },
    }

    priorities: dict[str, list[str]] = {"high": [], "medium": [], "low": []}
    labels = {"ci_cd": "CI/CD", "tests": "Tests", "security": "Security", "code_quality": "Code quality"}
    for key, finding in findings.items():
        priorities[str(finding["attention"])].append(labels[key])

    return {"findings": findings, "priorities": priorities}


def _format_inspection_report(result: dict[str, Any], workspace: Path) -> str:
    inspection = _repository_inspection(workspace)
    findings = inspection["findings"]
    priorities = inspection["priorities"]
    status = str(result.get("status") or "unknown").upper()

    def priority_text(level: str) -> str:
        values = priorities[level]
        return ", ".join(values) if values else "None detected by this baseline scan"

    return (
        f"**Status:** **{status}**\n\n"
        "## Repository findings\n\n"
        "### 1. CI/CD\n"
        f"- **Found:** {findings['ci_cd']['found']}\n"
        f"- **Recommended action:** {findings['ci_cd']['recommendation']}\n\n"
        "### 2. Tests\n"
        f"- **Found:** {findings['tests']['found']}\n"
        f"- **Recommended action:** {findings['tests']['recommendation']}\n\n"
        "### 3. Security\n"
        f"- **Found:** {findings['security']['found']}\n"
        f"- **Recommended action:** {findings['security']['recommendation']}\n\n"
        "### 4. Code quality\n"
        f"- **Found:** {findings['code_quality']['found']}\n"
        f"- **Recommended action:** {findings['code_quality']['recommendation']}\n\n"
        "## Priority\n"
        f"- **HIGH:** {priority_text('high')}\n"
        f"- **MEDIUM:** {priority_text('medium')}\n"
        f"- **LOW:** {priority_text('low')}\n\n"
        "## Recommended next action\n"
        "Tell me naturally what you want next, or use `@amosclaud fix <specific problem>` for a targeted repair."
    )[:6000]


class AmosclaudBot:
    """GitHub-native autonomous assistant for the repository-local Amosclaud runtime."""

    def __init__(self, repository: str, token: str = "", workspace: Path | str = ".") -> None:
        self.repository = repository
        self.token = token
        self.workspace = Path(workspace).resolve()
        self.api = os.getenv("GITHUB_API_URL", "https://api.github.com").rstrip("/")

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        if not self.token:
            raise RuntimeError("GITHUB_TOKEN is not configured")
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            f"{self.api}{path}",
            data=data,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "amosclaud-bot",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"GitHub API request failed ({exc.code}): {detail[:500]}") from exc

    def post_comment(self, issue_number: int, body: str) -> None:
        self._request("POST", f"/repos/{self.repository}/issues/{issue_number}/comments", {"body": body})

    def _run_local(self, command: str, objective: str, *, allow_writes: bool) -> dict[str, Any]:
        kernel = get_autonomous_kernel(self.workspace)
        metadata = {
            "source": "amosclaud-bot",
            "repository": self.repository,
            "github_run_id": os.getenv("GITHUB_RUN_ID", ""),
        }
        if command == "fix":
            if not allow_writes:
                return {
                    "status": "blocked",
                    "error": "write_not_authorized",
                    "evidence": ["Amosclaud-Fixer is available, but repository writes are limited to trusted repository collaborators."],
                }
            return kernel.repair(issue=objective, authorized_writes=True)

        mode = {"inspect": "plan", "review": "review", "verify": "verify"}.get(command, "plan")
        return kernel.execute(
            objective=objective,
            mode=mode,
            authorized_writes=False,
            metadata=metadata,
        )

    def handle_comment(self, payload: dict[str, Any]) -> BotResponse:
        comment = payload.get("comment") or {}
        command, objective = parse_command(str(comment.get("body") or ""))
        if not command:
            return BotResponse("", should_comment=False)

        issue = payload.get("issue") or {}
        number = issue.get("number", "unknown")
        is_pr = bool(issue.get("pull_request"))
        target = f"pull request #{number}" if is_pr else f"issue #{number}"
        association = str(comment.get("author_association") or "NONE").upper()
        trusted_writer = association in WRITE_ASSOCIATIONS

        if command == "help":
            return BotResponse(
                "### Amosclaud Autonomous Assistant\n"
                "I work directly inside this GitHub repository through GitHub Actions. The website is not required.\n\n"
                "You can talk to me naturally after `@amosclaud`. For example:\n\n"
                "- `@amosclaud my tests started failing after the last merge, inspect the problem`\n"
                "- `@amosclaud fix the failing authentication test and add a regression test`\n"
                "- `@amosclaud create a repository health-check file and test it`\n"
                "- `@amosclaud review this PR and tell me what is risky`\n\n"
                "Explicit commands still work: `status`, `inspect`, `review`, `verify`, and `fix`. "
                "Sensitive/private work still goes through the approval and privacy gates."
            )

        kernel = get_autonomous_kernel(self.workspace)
        if command == "status":
            status = kernel.status()
            return BotResponse(
                "### Amosclaud Autonomous Assistant — Status\n"
                "- GitHub Actions runner: **ready**\n"
                "- Website dependency: **none**\n"
                f"- Repository: `{self.repository}`\n"
                f"- Target: {target}\n"
                f"- Amosclaud Autonomous: **{status.get('status', 'unknown')}**\n"
                "- Amosclaud-Fixer: **available through Autonomous repair**\n"
                "- Natural-language assistant mode: **enabled**\n"
                f"- Workspace: `{status.get('workspace', self.workspace)}`"
            )

        request_objective = objective or f"{command.capitalize()} {target}"
        result = self._run_local(command, request_objective, allow_writes=trusted_writer)
        engine = "Amosclaud-Fixer" if command == "fix" else "Amosclaud Autonomous"
        details = _format_inspection_report(result, self.workspace) if command == "inspect" else _summarize_result(result)
        return BotResponse(
            f"### Amosclaud Autonomous Assistant — {command.capitalize()}\n\n"
            f"**Engine:** {engine}\n"
            f"**Understood objective:** {request_objective}\n\n"
            f"{details}"
        )

    def handle_workflow_run(self, payload: dict[str, Any]) -> tuple[int | None, BotResponse]:
        run = payload.get("workflow_run") or {}
        if run.get("action") == "requested" or run.get("conclusion") != "failure":
            return None, BotResponse("", should_comment=False)
        prs = run.get("pull_requests") or []
        if not prs:
            return None, BotResponse("", should_comment=False)
        number = prs[0].get("number")
        if not isinstance(number, int):
            return None, BotResponse("", should_comment=False)
        name = run.get("name") or "GitHub Actions"
        url = run.get("html_url") or ""
        body = (
            "### Amosclaud Autonomous Assistant detected a CI failure\n"
            f"Workflow **{name}** failed for this pull request.\n\n"
            f"Run: {url}\n\n"
            "Tell me naturally what you want me to do, for example `@amosclaud inspect this CI failure` "
            "or `@amosclaud fix this CI failure and verify the repair`."
        )
        return number, BotResponse(body)


def run_from_environment() -> int:
    event_name = os.getenv("GITHUB_EVENT_NAME", "")
    event_path = os.getenv("GITHUB_EVENT_PATH", "")
    repository = os.getenv("GITHUB_REPOSITORY", "")
    token = os.getenv("GITHUB_TOKEN", "")
    if not event_path or not repository:
        raise RuntimeError("GITHUB_EVENT_PATH and GITHUB_REPOSITORY are required")
    payload = json.loads(Path(event_path).read_text(encoding="utf-8"))
    bot = AmosclaudBot(repository=repository, token=token, workspace=Path.cwd())

    if event_name == "issue_comment":
        number = int((payload.get("issue") or {}).get("number"))
        response = bot.handle_comment(payload)
        if response.should_comment:
            bot.post_comment(number, response.body)
        return 0

    if event_name == "workflow_run":
        number, response = bot.handle_workflow_run(payload)
        if number is not None and response.should_comment:
            bot.post_comment(number, response.body)
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(run_from_environment())

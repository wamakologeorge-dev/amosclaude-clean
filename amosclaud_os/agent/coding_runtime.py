"""Real model-backed coding runtime for native Amosclaud repositories.

The runtime is deliberately bounded:

* it receives a server-authorized native repository path;
* it asks the configured model for a strict JSON change set;
* it rejects path escapes, protected paths, deletions, duplicate paths, and
  oversized proposals;
* it writes on a new Git branch, runs deterministic verification, and commits
  only when every discovered check passes;
* it rolls the repository back to the source branch on any failure.

It never substitutes the Amosclaud platform source when a project is missing.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from git import Repo

from src.services.file_manager import SafeFileManager

_SKIP_PARTS = {
    ".git",
    ".idea",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "build",
    "data",
    "dist",
    "node_modules",
    "secrets",
    "venv",
}
_TEXT_SUFFIXES = {
    "",
    ".c",
    ".cc",
    ".cfg",
    ".conf",
    ".cpp",
    ".css",
    ".go",
    ".h",
    ".hpp",
    ".html",
    ".ini",
    ".java",
    ".js",
    ".json",
    ".jsx",
    ".md",
    ".mjs",
    ".py",
    ".rb",
    ".rs",
    ".sh",
    ".sql",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}
_BRANCH_TOKEN = re.compile(r"[^a-z0-9-]+")
_MAX_CHANGE_BYTES = 2_000_000


def _sensitive_path(path: Path) -> bool:
    for part in path.parts:
        lowered = part.lower()
        if lowered.startswith(".env"):
            return True
        if lowered in {"credentials.json", "id_rsa", "id_ed25519"}:
            return True
        if any(token in lowered for token in ("secret", "credential", "private-key")):
            return True
    return path.suffix.lower() in {".key", ".pem", ".p12", ".pfx"}


@dataclass(frozen=True)
class CodingChange:
    path: str
    content: str
    reason: str = ""


@dataclass(frozen=True)
class CodingProposal:
    plan: list[str]
    changes: list[CodingChange]
    commit_message: str


@dataclass
class CodingRuntimeResult:
    status: str
    source_branch: str
    branch: str | None = None
    commit: str | None = None
    plan: list[str] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)
    checks: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    blocker: str | None = None
    model: dict[str, Any] = field(default_factory=dict)

    @property
    def succeeded(self) -> bool:
        return self.status == "success" and bool(self.commit)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AutonomousCodingRuntime:
    """Generate, apply, verify, and commit one bounded model change set."""

    def __init__(
        self,
        workspace: Path,
        *,
        model,
        max_files: int = 12,
        max_context_chars: int = 120_000,
    ) -> None:
        self.workspace = workspace.resolve()
        self.model = model
        self.max_files = max(1, min(int(max_files), 24))
        self.max_context_chars = max(10_000, min(int(max_context_chars), 500_000))
        self.files = SafeFileManager(self.workspace)

    def run(
        self,
        *,
        objective: str,
        source_branch: str,
        author_name: str,
        author_email: str,
    ) -> CodingRuntimeResult:
        clean_objective = " ".join((objective or "").strip().split())
        clean_source = (source_branch or "main").strip()
        result = CodingRuntimeResult(
            status="failed",
            source_branch=clean_source,
            model=self._model_description(),
        )
        repo: Repo | None = None
        branch_name: str | None = None
        base_commit: str | None = None

        try:
            if not clean_objective:
                raise ValueError("A coding objective is required")
            if not (self.workspace / ".git").is_dir():
                raise ValueError("The selected workspace is not a native Git repository")

            repo = Repo(self.workspace)
            heads = {head.name for head in repo.heads}
            if clean_source not in heads:
                raise ValueError(f"Source branch does not exist: {clean_source}")

            self._restore_source(repo, clean_source)
            base_commit = repo.head.commit.hexsha

            evidence = self._repository_evidence()
            raw = self.model.complete(
                self._proposal_instruction(clean_objective),
                evidence,
            )
            proposal = self._parse_proposal(raw)
            effective_changes = self._validate_changes(proposal.changes)
            if not effective_changes:
                raise ValueError("The model did not produce any real file changes")

            branch_name = self._available_branch(repo, clean_objective, base_commit)
            repo.create_head(branch_name, repo.head.commit)
            repo.git.checkout(branch_name)
            result.branch = branch_name
            result.plan = proposal.plan

            for change in effective_changes:
                self.files.write(change.path, change.content, authorized=True)

            result.changed_files = [change.path for change in effective_changes]
            result.checks = self._verify(effective_changes)
            failures = [check for check in result.checks if not bool(check.get("passed"))]
            if failures:
                blocker = str(failures[0].get("summary") or "Verification failed")
                raise RuntimeError(f"Verification failed: {blocker}")

            repo.git.add(A=True)
            if not repo.is_dirty(untracked_files=True):
                raise ValueError(
                    "The proposed content matches the repository; no commit was created"
                )

            with repo.config_writer() as config:
                config.set_value("user", "name", author_name or author_email)
                config.set_value("user", "email", author_email)
            commit = repo.index.commit(proposal.commit_message).hexsha
            result.checks.append(
                {
                    "name": "git-commit",
                    "passed": True,
                    "exit_code": 0,
                    "summary": f"Created commit {commit[:12]} on {branch_name}.",
                    "output": commit,
                }
            )

            result.status = "success"
            result.commit = commit
            result.evidence = [
                f"Source branch: {clean_source}",
                f"Execution branch: {branch_name}",
                f"Base commit: {base_commit}",
                f"Created commit: {commit}",
                *(f"Changed file: {path}" for path in result.changed_files),
                *(
                    f"Check passed: {check.get('name')} — {check.get('summary')}"
                    for check in result.checks
                    if check.get("passed")
                ),
            ]
            return result
        except Exception as exc:
            result.blocker = str(exc)
            result.evidence = [
                f"Source branch: {clean_source}",
                "No verified coding success was reported.",
                f"Blocker: {type(exc).__name__}: {exc}",
            ]
            if repo is not None:
                self._rollback(repo, clean_source, branch_name, base_commit)
            result.branch = None
            result.commit = None
            result.changed_files = []
            return result

    def _model_description(self) -> dict[str, Any]:
        describe = getattr(self.model, "describe", None)
        if callable(describe):
            value = describe()
            if isinstance(value, dict):
                return dict(value)
        return {"mode": type(self.model).__name__}

    def _repository_evidence(self) -> list[str]:
        paths: list[str] = []
        documents: list[str] = []
        used = 0

        for item in sorted(self.workspace.rglob("*")):
            if not item.is_file():
                continue
            relative = item.relative_to(self.workspace)
            if any(part in _SKIP_PARTS for part in relative.parts) or _sensitive_path(relative):
                continue
            relative_text = relative.as_posix()
            paths.append(relative_text)
            if len(paths) > 300:
                continue
            if item.suffix.lower() not in _TEXT_SUFFIXES:
                continue
            try:
                if item.stat().st_size > 64_000:
                    continue
                raw = item.read_bytes()
                if b"\x00" in raw:
                    continue
                content = raw.decode("utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            available = self.max_context_chars - used
            if available <= 0:
                break
            excerpt = content[:available]
            documents.append(f"FILE {relative_text}\n{excerpt}")
            used += len(excerpt)

        tree = "\n".join(paths[:300]) or "(empty repository)"
        return [
            "REPOSITORY TREE\n" + tree,
            *documents,
        ]

    def _proposal_instruction(self, objective: str) -> str:
        return (
            "Act as the execution model for a native Amosclaud repository. "
            "Return exactly one JSON object and no Markdown. The object must use this shape: "
            '{"plan":["step"],"changes":[{"path":"relative/path","content":"complete file content",'
            '"reason":"why"}],"commit_message":"imperative summary"}. '
            f"Produce between 1 and {self.max_files} complete-file changes. "
            "Use only relative repository paths. Never modify .git, .env, data, secrets, "
            "dependency caches, generated build output, or files outside the repository. "
            "Do not request deletion, shell commands, deployments, merges, credentials, or "
            "network access. Preserve unrelated behavior and include focused tests when the "
            "repository supports them. The runtime, not the model, will write files, run "
            f"verification, and create the commit. Requested objective: {objective}"
        )

    def _parse_proposal(self, raw: str) -> CodingProposal:
        text = str(raw or "").strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        if not text.startswith("{"):
            start = text.find("{")
            end = text.rfind("}")
            if start < 0 or end <= start:
                raise ValueError("Model response did not contain a JSON object")
            text = text[start : end + 1]

        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Model response was not valid JSON: {exc.msg}") from exc
        if not isinstance(payload, dict):
            raise ValueError("Model response must be a JSON object")

        plan_raw = payload.get("plan")
        changes_raw = payload.get("changes")
        if not isinstance(plan_raw, list) or not plan_raw:
            raise ValueError("Model proposal must include a non-empty plan")
        if not isinstance(changes_raw, list) or not changes_raw:
            raise ValueError("Model proposal must include a non-empty changes list")
        if len(changes_raw) > self.max_files:
            raise ValueError(f"Model proposal exceeds the {self.max_files}-file limit")

        plan = [str(item).strip() for item in plan_raw[:12] if str(item).strip()]
        changes: list[CodingChange] = []
        for item in changes_raw:
            if not isinstance(item, dict):
                raise ValueError("Every proposed change must be an object")
            path = item.get("path")
            content = item.get("content")
            if not isinstance(path, str) or not isinstance(content, str):
                raise ValueError("Every proposed change requires path and complete content")
            changes.append(
                CodingChange(
                    path=path.strip(),
                    content=content,
                    reason=str(item.get("reason") or "").strip(),
                )
            )

        message = " ".join(str(payload.get("commit_message") or "").split())[:200]
        if not message:
            message = "Implement requested change with Amosclaud"
        return CodingProposal(plan=plan, changes=changes, commit_message=message)

    def _validate_changes(self, changes: list[CodingChange]) -> list[CodingChange]:
        seen: set[str] = set()
        effective: list[CodingChange] = []
        for change in changes:
            if not change.path:
                raise ValueError("A proposed file path is empty")
            target = self.files.resolve(change.path)
            relative_path = target.relative_to(self.workspace)
            relative = relative_path.as_posix()
            if _sensitive_path(relative_path):
                raise ValueError(f"Sensitive path cannot be modified: {relative}")
            if relative in seen:
                raise ValueError(f"Duplicate proposed path: {relative}")
            seen.add(relative)
            if len(change.content.encode("utf-8")) > _MAX_CHANGE_BYTES:
                raise ValueError(f"Proposed file is too large: {relative}")
            existing = None
            if target.is_file():
                try:
                    existing = target.read_text(encoding="utf-8")
                except UnicodeDecodeError as exc:
                    raise ValueError(f"Binary file cannot be replaced: {relative}") from exc
            if existing == change.content:
                continue
            effective.append(CodingChange(relative, change.content, change.reason))
        return effective

    def _available_branch(self, repo: Repo, objective: str, base_commit: str) -> str:
        words = _BRANCH_TOKEN.sub(
            "-",
            objective.lower(),
        ).strip("-")
        words = "-".join(words.split("-")[:6])[:48] or "change"
        digest = hashlib.sha256(f"{objective}\0{base_commit}".encode("utf-8")).hexdigest()[:8]
        base = f"amosclaud/agent-{words}-{digest}"
        existing = {head.name for head in repo.heads}
        if base not in existing:
            return base
        for number in range(2, 100):
            candidate = f"{base}-{number}"
            if candidate not in existing:
                return candidate
        raise RuntimeError("Could not allocate a unique execution branch")

    def _verify(self, changes: list[CodingChange]) -> list[dict[str, Any]]:
        checks: list[dict[str, Any]] = [
            {
                "name": "change-set",
                "passed": bool(changes),
                "exit_code": 0 if changes else 1,
                "summary": f"Validated {len(changes)} bounded complete-file change(s).",
                "output": "\n".join(change.path for change in changes),
            }
        ]

        python_paths = [change.path for change in changes if Path(change.path).suffix == ".py"]
        if python_paths:
            checks.append(
                self._run_check(
                    "python-syntax",
                    [sys.executable, "-m", "py_compile", *python_paths],
                    timeout=90,
                )
            )

        for change in changes:
            if Path(change.path).suffix.lower() == ".json":
                try:
                    json.loads(change.content)
                except json.JSONDecodeError as exc:
                    checks.append(
                        {
                            "name": f"json:{change.path}",
                            "passed": False,
                            "exit_code": 1,
                            "summary": f"Invalid JSON at line {exc.lineno}: {exc.msg}",
                            "output": str(exc),
                        }
                    )
                else:
                    checks.append(
                        {
                            "name": f"json:{change.path}",
                            "passed": True,
                            "exit_code": 0,
                            "summary": "JSON parsed successfully.",
                            "output": "",
                        }
                    )

        javascript_paths = [
            change.path
            for change in changes
            if Path(change.path).suffix.lower() in {".js", ".mjs", ".cjs"}
        ]
        node = shutil.which("node")
        for path in javascript_paths:
            if node:
                checks.append(
                    self._run_check(
                        f"node-syntax:{path}", [node, "--check", path], timeout=60
                    )
                )

        tests = list(self.workspace.glob("tests/test_*.py"))
        tests.extend(self.workspace.glob("tests/**/*_test.py"))
        if tests and (
            (self.workspace / "pyproject.toml").exists()
            or (self.workspace / "pytest.ini").exists()
            or (self.workspace / "setup.cfg").exists()
        ):
            checks.append(
                self._run_check(
                    "pytest",
                    [sys.executable, "-m", "pytest", "-q"],
                    timeout=180,
                )
            )

        if len(checks) == 1:
            checks.append(
                {
                    "name": "repository-structure",
                    "passed": all((self.workspace / change.path).is_file() for change in changes),
                    "exit_code": 0,
                    "summary": (
                        "Changed files exist inside the authorized repository. "
                        "No supported project test runner was discovered."
                    ),
                    "output": "",
                }
            )
        return checks

    def _run_check(self, name: str, command: list[str], *, timeout: int) -> dict[str, Any]:
        try:
            completed = subprocess.run(
                command,
                cwd=self.workspace,
                text=True,
                capture_output=True,
                check=False,
                timeout=timeout,
            )
            output = (completed.stdout + "\n" + completed.stderr).strip()[-12_000:]
            return {
                "name": name,
                "passed": completed.returncode == 0,
                "exit_code": completed.returncode,
                "command": " ".join(command),
                "summary": (
                    output.splitlines()[-1]
                    if output
                    else f"{name} exited with code {completed.returncode}"
                ),
                "output": output,
            }
        except subprocess.TimeoutExpired as exc:
            return {
                "name": name,
                "passed": False,
                "exit_code": 124,
                "command": " ".join(command),
                "summary": f"{name} exceeded the {timeout}-second limit",
                "output": str(exc),
            }

    @staticmethod
    def _restore_source(repo: Repo, source_branch: str) -> None:
        repo.git.reset("--hard")
        repo.git.clean("-fd")
        repo.git.checkout(source_branch)
        repo.git.reset("--hard", source_branch)
        repo.git.clean("-fd")

    def _rollback(
        self,
        repo: Repo,
        source_branch: str,
        branch_name: str | None,
        base_commit: str | None,
    ) -> None:
        try:
            if base_commit:
                repo.git.reset("--hard", base_commit)
            repo.git.clean("-fd")
            if source_branch in {head.name for head in repo.heads}:
                repo.git.checkout(source_branch)
                repo.git.reset("--hard", source_branch)
                repo.git.clean("-fd")
            if branch_name and branch_name in {head.name for head in repo.heads}:
                repo.delete_head(branch_name, force=True)
        except Exception:
            # Preserve the original blocker. The caller receives a failed result and
            # no success claim even when cleanup itself needs operator attention.
            pass

"""Plan, execute, verify, and publish one governed repository change.

This is the product-level facade that the older conversational service was
missing.  It deliberately owns orchestration, while the existing
``AutonomousCodingRuntime`` remains the single implementation responsible for
model proposals, protected paths, file writes, verification, and commits.

The service has two delivery modes:

* ``branch`` writes and verifies a local native repository branch;
* ``pull_request`` works from a fresh authenticated GitHub clone, verifies the
  result, pushes a new branch, and creates a PR.  It never merges.

No result is reported as completed without a commit and the verification
evidence produced by the coding runtime.
"""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
import tempfile
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol

import httpx
from git import Repo
from git.exc import GitCommandError, InvalidGitRepositoryError

from amosclaud_os.agent.coding_runtime import AutonomousCodingRuntime
from amoscloud_ai.github_git_auth import authenticated_git, git_auth_environment

_BRANCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$")
_GITHUB_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}$")
_SKIP_PARTS = {
    ".git",
    ".amosclaud",
    ".pytest_cache",
    "__pycache__",
    "data",
    "dist",
    "build",
    "node_modules",
    "secrets",
    "venv",
    ".venv",
}


class ExecutorError(RuntimeError):
    """Raised for a safe, user-actionable executor failure."""


@dataclass(frozen=True)
class RepositoryTarget:
    """A repository selected by the authenticated platform, never by a path string."""

    name: str
    workspace: Path | None = None
    default_branch: str = "main"
    github_full_name: str | None = None
    github_token: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.workspace is None and not self.github_full_name:
            raise ValueError("A native workspace or GitHub repository is required")
        if self.github_full_name and not _GITHUB_REPOSITORY_RE.fullmatch(self.github_full_name):
            raise ValueError("GitHub repository name is invalid")
        if self.github_full_name and not self.github_token:
            raise ValueError("A connected GitHub credential is required")
        _validate_branch(self.default_branch)

    @property
    def is_github(self) -> bool:
        return bool(self.github_full_name)

    @property
    def remote_url(self) -> str:
        if not self.github_full_name:
            raise ExecutorError("The target has no GitHub remote")
        return f"https://github.com/{self.github_full_name}.git"

    @property
    def key(self) -> str:
        if self.github_full_name:
            return f"github:{self.github_full_name.lower()}"
        if self.workspace is None:
            raise ExecutorError("The target has no native workspace")
        return f"workspace:{self.workspace.resolve()}"


@dataclass
class ExecutionResult:
    """Public, evidence-bearing result for both planning and execution."""

    run_id: str
    status: str
    summary: str
    objective: str
    target: str
    source_branch: str
    plan_id: str | None = None
    plan: list[str] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)
    checks: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    branch: str | None = None
    commit: str | None = None
    pull_request_url: str | None = None
    model: dict[str, Any] = field(default_factory=dict)
    delivery: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.status == "completed" and bool(self.commit)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class _PlanRecord:
    plan_id: str
    objective: str
    target_key: str
    source_branch: str
    target_name: str
    plan: tuple[str, ...]
    expires_at: float


class PlanStore(Protocol):
    """Storage contract for plans awaiting explicit execution confirmation."""

    def save(self, record: _PlanRecord) -> None: ...

    def get(self, plan_id: str) -> _PlanRecord | None: ...

    def consume(self, plan_id: str) -> _PlanRecord | None: ...

    def pending_count(self) -> int: ...


class MemoryPlanStore:
    """Small default store for embedded/standalone callers and unit tests."""

    def __init__(self) -> None:
        self._records: dict[str, _PlanRecord] = {}
        self._lock = threading.RLock()

    def save(self, record: _PlanRecord) -> None:
        with self._lock:
            self._records[record.plan_id] = record

    def get(self, plan_id: str) -> _PlanRecord | None:
        with self._lock:
            record = self._records.get(plan_id)
            if record is None:
                return None
            if record.expires_at <= time.time():
                self._records.pop(plan_id, None)
                return None
            return record

    def consume(self, plan_id: str) -> _PlanRecord | None:
        with self._lock:
            record = self.get(plan_id)
            if record is None:
                return None
            return self._records.pop(plan_id, None)

    def pending_count(self) -> int:
        with self._lock:
            for plan_id in list(self._records):
                self.get(plan_id)
            return len(self._records)


class SQLitePlanStore:
    """Durable plan store used by the authenticated FastAPI application."""

    def __init__(self, path: Path | str, *, ttl_seconds: int = 900) -> None:
        self.path = Path(path)
        self.ttl_seconds = max(60, min(int(ttl_seconds), 3600))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS amosclaud_executor_plans (
                    plan_id TEXT PRIMARY KEY,
                    objective TEXT NOT NULL,
                    target_key TEXT NOT NULL,
                    source_branch TEXT NOT NULL,
                    target_name TEXT NOT NULL,
                    plan_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    consumed_at REAL
                )""")
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_executor_plans_expiry "
                "ON amosclaud_executor_plans(expires_at, consumed_at)"
            )
            db.commit()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def save(self, record: _PlanRecord) -> None:
        with self._connect() as db:
            now = time.time()
            db.execute(
                "DELETE FROM amosclaud_executor_plans "
                "WHERE expires_at<=? OR consumed_at IS NOT NULL",
                (now,),
            )
            db.execute(
                """INSERT INTO amosclaud_executor_plans(
                    plan_id,objective,target_key,source_branch,target_name,plan_json,
                    created_at,expires_at,consumed_at
                ) VALUES (?,?,?,?,?,?,?,?,NULL)""",
                (
                    record.plan_id,
                    record.objective,
                    record.target_key,
                    record.source_branch,
                    record.target_name,
                    json.dumps(list(record.plan), ensure_ascii=False),
                    now,
                    record.expires_at,
                ),
            )
            db.commit()

    def get(self, plan_id: str) -> _PlanRecord | None:
        with self._connect() as db:
            row = db.execute(
                """SELECT plan_id,objective,target_key,source_branch,target_name,
                   plan_json,expires_at
                   FROM amosclaud_executor_plans
                   WHERE plan_id=? AND consumed_at IS NULL AND expires_at>?""",
                (plan_id, time.time()),
            ).fetchone()
        return self._record(row)

    def consume(self, plan_id: str) -> _PlanRecord | None:
        with self._connect() as db:
            now = time.time()
            row = db.execute(
                """SELECT plan_id,objective,target_key,source_branch,target_name,
                   plan_json,expires_at
                   FROM amosclaud_executor_plans
                   WHERE plan_id=? AND consumed_at IS NULL AND expires_at>?""",
                (plan_id, now),
            ).fetchone()
            if row is None:
                return None
            updated = db.execute(
                """UPDATE amosclaud_executor_plans SET consumed_at=?
                   WHERE plan_id=? AND consumed_at IS NULL AND expires_at>?""",
                (now, plan_id, now),
            )
            if updated.rowcount != 1:
                db.rollback()
                return None
            db.commit()
        return self._record(row)

    def pending_count(self) -> int:
        with self._connect() as db:
            row = db.execute(
                """SELECT COUNT(*) AS count FROM amosclaud_executor_plans
                   WHERE consumed_at IS NULL AND expires_at>?""",
                (time.time(),),
            ).fetchone()
        return int(row["count"] if row else 0)

    @staticmethod
    def _record(row: sqlite3.Row | None) -> _PlanRecord | None:
        if row is None:
            return None
        try:
            plan = json.loads(row["plan_json"])
        except (TypeError, json.JSONDecodeError):
            return None
        if not isinstance(plan, list):
            return None
        return _PlanRecord(
            plan_id=str(row["plan_id"]),
            objective=str(row["objective"]),
            target_key=str(row["target_key"]),
            source_branch=str(row["source_branch"]),
            target_name=str(row["target_name"]),
            plan=tuple(str(item) for item in plan),
            expires_at=float(row["expires_at"]),
        )


class GatewayCodingModel:
    """Adapt the shared Amosclaud model gateway to the coding runtime contract."""

    def __init__(self, gateway: Any | None = None) -> None:
        if gateway is None:
            from src.agent.model import AutonomousModelGateway

            gateway = AutonomousModelGateway()
        self.gateway = gateway

    def describe(self) -> dict[str, Any]:
        describe = getattr(self.gateway, "describe", None)
        if callable(describe):
            value = describe()
            if isinstance(value, dict):
                return dict(value)
        return {"mode": type(self.gateway).__name__}

    def complete(self, instruction: str, evidence: list[str]) -> str:
        raw = self.gateway.complete(instruction, evidence)
        payload = _json_payload(raw)
        if not isinstance(payload, dict):
            return str(raw)

        # The shared gateway uses diagnosis/verification while the native
        # coding runtime uses plan/commit_message.  Convert at this boundary so
        # there is still only one model provider and one write runtime.
        plan = payload.get("plan")
        if not isinstance(plan, list) or not plan:
            plan = []
            diagnosis = str(payload.get("diagnosis") or "").strip()
            if diagnosis:
                plan.append(diagnosis)
            verification = payload.get("verification")
            if isinstance(verification, list):
                plan.extend(str(item).strip() for item in verification if str(item).strip())
            if not plan:
                plan = ["Apply the bounded change and run repository verification"]

        commit_message = str(payload.get("commit_message") or "").strip()
        if not commit_message:
            changes = payload.get("changes")
            first_path = ""
            if isinstance(changes, list) and changes and isinstance(changes[0], dict):
                first_path = str(changes[0].get("path") or "").strip()
            commit_message = f"Amosclaud: update {first_path}".strip()
            if commit_message == "Amosclaud: update":
                commit_message = "Amosclaud: apply verified repository change"

        normalized = {
            "plan": plan[:12],
            "changes": payload.get("changes"),
            "commit_message": commit_message[:200],
        }
        return json.dumps(normalized, ensure_ascii=False)


class ExecutorService:
    """The one governed product facade for repository engineering work."""

    DEFAULT_PLAN = (
        "Inspect the selected repository and source branch.",
        "Reproduce or analyze the requested failure with bounded evidence.",
        "Ask the configured Amosclaud model for a minimal complete-file proposal.",
        "Apply only safe files inside an isolated execution branch.",
        "Run deterministic verification and keep the commit only if every check passes.",
        "Publish the verified branch as a pull request when GitHub delivery is selected.",
    )

    def __init__(
        self,
        *,
        model: Any | None = None,
        plan_store: PlanStore | None = None,
        runtime_class: type[AutonomousCodingRuntime] = AutonomousCodingRuntime,
        github_timeout_seconds: float = 30.0,
    ) -> None:
        self.model = model or GatewayCodingModel()
        self.plan_store = plan_store or MemoryPlanStore()
        self.runtime_class = runtime_class
        self.github_timeout_seconds = max(5.0, min(float(github_timeout_seconds), 120.0))
        self._lock = threading.RLock()

    @property
    def pending_plan_count(self) -> int:
        return self.plan_store.pending_count()

    def capabilities(self) -> dict[str, Any]:
        describe = getattr(self.model, "describe", None)
        model = describe() if callable(describe) else {"mode": type(self.model).__name__}
        return {
            "product": "Amosclaud-executor",
            "model": model,
            "deliveries": ["branch", "pull_request"],
            "verification_required": True,
            "merge_supported": False,
            "protected_paths": True,
            "plan_confirmation": "Proceed",
        }

    def plan(
        self,
        target: RepositoryTarget,
        objective: str,
        *,
        source_branch: str | None = None,
    ) -> ExecutionResult:
        clean_objective = _clean_objective(objective)
        branch = _validate_branch(source_branch or target.default_branch)
        run_id = "planrun_" + uuid.uuid4().hex
        blockers, evidence = self._inspect(target, branch)
        plan_id = "plan_" + uuid.uuid4().hex
        plan = list(self.DEFAULT_PLAN)
        if target.is_github:
            plan[0] = "Clone the selected GitHub repository at the requested source branch."
        else:
            plan[-1] = "Return the verified local branch commit for review."

        if not blockers:
            self.plan_store.save(
                _PlanRecord(
                    plan_id=plan_id,
                    objective=clean_objective,
                    target_key=target.key,
                    source_branch=branch,
                    target_name=target.name,
                    plan=tuple(plan),
                    expires_at=time.time() + 900,
                )
            )
            status = "planned"
            summary = "Plan ready. No repository files were changed."
        else:
            status = "blocked"
            summary = (
                "Planning stopped before execution because the repository target is not ready."
            )

        return ExecutionResult(
            run_id=run_id,
            status=status,
            summary=summary,
            objective=clean_objective,
            target=target.name,
            source_branch=branch,
            plan_id=plan_id if not blockers else None,
            plan=plan,
            evidence=evidence,
            blockers=blockers,
            model=self._model_description(),
        )

    def execute(
        self,
        target: RepositoryTarget,
        objective: str,
        *,
        plan_id: str | None,
        confirmation: str,
        source_branch: str | None = None,
        delivery: str = "pull_request",
        author_name: str = "Amosclaud",
        author_email: str = "amosclaud@localhost",
        pull_request_title: str | None = None,
        pull_request_body: str | None = None,
        draft: bool = True,
    ) -> ExecutionResult:
        clean_objective = _clean_objective(objective)
        branch = _validate_branch(source_branch or target.default_branch)
        if confirmation.strip() != "Proceed":
            return self._blocked(
                clean_objective,
                target,
                branch,
                "Execution requires the exact confirmation 'Proceed'. No files were changed.",
            )

        with self._lock:
            record = self.plan_store.get(str(plan_id or ""))

        if record is None:
            return self._blocked(
                clean_objective,
                target,
                branch,
                (
                    "The execution plan is missing or already used. "
                    "Create a fresh plan before running."
                ),
            )
        if record.target_key != target.key or record.target_name != target.name:
            return self._blocked(
                clean_objective,
                target,
                branch,
                "The execution target does not match the approved plan. Create a fresh plan.",
                plan=list(record.plan),
                plan_id=record.plan_id,
            )
        if record.source_branch != branch or record.objective != clean_objective:
            return self._blocked(
                clean_objective,
                target,
                branch,
                "The objective or source branch changed after planning. Create a fresh plan.",
                plan=list(record.plan),
                plan_id=record.plan_id,
            )
        if delivery not in {"branch", "pull_request"}:
            return self._blocked(
                clean_objective,
                target,
                branch,
                "Delivery must be 'branch' or 'pull_request'.",
                plan=list(record.plan),
                plan_id=record.plan_id,
            )
        if delivery == "pull_request" and not target.is_github:
            return self._blocked(
                clean_objective,
                target,
                branch,
                "Pull-request delivery requires a connected GitHub repository.",
                plan=list(record.plan),
                plan_id=record.plan_id,
            )
        if delivery == "branch" and target.is_github:
            return self._blocked(
                clean_objective,
                target,
                branch,
                (
                    "GitHub targets publish through pull-request delivery; no "
                    "unpublished remote branch was created."
                ),
                plan=list(record.plan),
                plan_id=record.plan_id,
            )

        # Consume a valid plan only once all request invariants have passed. A
        # typo in delivery or a mismatched target must not silently discard the
        # user's still-valid approval; concurrent callers still cannot reuse it.
        with self._lock:
            if self.plan_store.consume(record.plan_id) is None:
                return self._blocked(
                    clean_objective,
                    target,
                    branch,
                    (
                        "The execution plan is missing or already used. "
                        "Create a fresh plan before running."
                    ),
                    plan=list(record.plan),
                    plan_id=record.plan_id,
                )

        if target.is_github:
            return self._execute_github(
                target,
                clean_objective,
                branch,
                record,
                author_name=author_name,
                author_email=author_email,
                pull_request_title=pull_request_title,
                pull_request_body=pull_request_body,
                draft=draft,
            )
        return self._execute_local(
            target,
            clean_objective,
            branch,
            record,
            author_name=author_name,
            author_email=author_email,
        )

    def execute_direct(
        self,
        target: RepositoryTarget,
        objective: str,
        *,
        source_branch: str | None = None,
        delivery: str = "branch",
        author_name: str = "Amosclaud",
        author_email: str = "amosclaud@localhost",
    ) -> ExecutionResult:
        """Run the same plan/confirmation flow for trusted internal callers."""
        prepared = self.plan(target, objective, source_branch=source_branch)
        if prepared.status != "planned" or not prepared.plan_id:
            return prepared
        return self.execute(
            target,
            objective,
            plan_id=prepared.plan_id,
            confirmation="Proceed",
            source_branch=source_branch,
            delivery=delivery,
            author_name=author_name,
            author_email=author_email,
        )

    def _execute_local(
        self,
        target: RepositoryTarget,
        objective: str,
        source_branch: str,
        record: _PlanRecord,
        *,
        author_name: str,
        author_email: str,
    ) -> ExecutionResult:
        if target.workspace is None or not target.workspace.is_dir():
            return self._failed(
                objective,
                target,
                source_branch,
                record,
                "The selected native repository workspace does not exist.",
            )
        try:
            repo = Repo(target.workspace)
            if repo.is_dirty(untracked_files=True):
                return self._failed(
                    objective,
                    target,
                    source_branch,
                    record,
                    (
                        "The native repository has uncommitted changes; commit or "
                        "discard them before execution."
                    ),
                )
        except (InvalidGitRepositoryError, GitCommandError, OSError) as exc:
            return self._failed(
                objective,
                target,
                source_branch,
                record,
                f"The native repository could not be opened: {type(exc).__name__}.",
            )

        runtime = self.runtime_class(target.workspace, model=self.model)
        result = runtime.run(
            objective=objective,
            source_branch=source_branch,
            author_name=author_name or "Amosclaud",
            author_email=author_email or "amosclaud@localhost",
            branch_prefix=f"amosclaud/executor-{record.plan_id.removeprefix('plan_')[:12]}",
        )
        return self._from_runtime(result, target, objective, record, delivery="branch")

    def _execute_github(
        self,
        target: RepositoryTarget,
        objective: str,
        source_branch: str,
        record: _PlanRecord,
        *,
        author_name: str,
        author_email: str,
        pull_request_title: str | None,
        pull_request_body: str | None,
        draft: bool,
    ) -> ExecutionResult:
        if not target.github_full_name or not target.github_token:
            return self._failed(
                objective,
                target,
                source_branch,
                record,
                "The GitHub target is missing its connected repository credential.",
            )
        tempdir = Path(tempfile.mkdtemp(prefix=f"amosclaud-executor-{record.plan_id}-"))
        try:
            try:
                Repo.clone_from(
                    target.remote_url,
                    tempdir,
                    branch=source_branch,
                    depth=1,
                    env=git_auth_environment(target.github_token),
                )
                repo = Repo(tempdir)
                base_sha = repo.head.commit.hexsha
                repo.remote("origin").set_url(target.remote_url)
            except (GitCommandError, OSError, ValueError) as exc:
                return self._failed(
                    objective,
                    target,
                    source_branch,
                    record,
                    f"GitHub repository clone failed safely: {type(exc).__name__}.",
                )

            runtime = self.runtime_class(tempdir, model=self.model)
            result = runtime.run(
                objective=objective,
                source_branch=source_branch,
                author_name=author_name or "Amosclaud",
                author_email=author_email or "amosclaud@localhost",
                branch_prefix=f"amosclaud/executor-{record.plan_id.removeprefix('plan_')[:12]}",
            )
            if not result.succeeded or not result.branch or not result.commit:
                return self._from_runtime(
                    result, target, objective, record, delivery="pull_request"
                )

            try:
                self._assert_base_unchanged(
                    repo,
                    target.github_token,
                    source_branch,
                    base_sha,
                )
                self._push_branch(repo, target.github_token, result.branch)
                pull_request_url = self._create_pull_request(
                    target,
                    result.branch,
                    source_branch,
                    objective,
                    result,
                    title=pull_request_title,
                    body=pull_request_body,
                    draft=draft,
                )
            except ExecutorError as exc:
                failed = self._from_runtime(
                    result,
                    target,
                    objective,
                    record,
                    delivery="pull_request",
                )
                failed.status = "failed"
                failed.summary = "The code was verified, but GitHub publication did not complete."
                failed.blockers.append(str(exc))
                failed.evidence.append(f"Publication blocker: {exc}")
                return failed

            completed = self._from_runtime(
                result,
                target,
                objective,
                record,
                delivery="pull_request",
            )
            completed.status = "completed"
            completed.summary = "Verified repository change committed and pull request opened."
            completed.pull_request_url = pull_request_url
            completed.evidence.append(f"Pull request opened: {pull_request_url}")
            return completed
        finally:
            shutil.rmtree(tempdir, ignore_errors=True)

    @staticmethod
    def _assert_base_unchanged(
        repo: Repo,
        token: str,
        source_branch: str,
        expected_sha: str,
    ) -> None:
        try:
            with authenticated_git(repo, token):
                repo.git.fetch("origin", source_branch, depth=1)
            current_sha = repo.commit(f"origin/{source_branch}").hexsha
        except (GitCommandError, ValueError) as exc:
            raise ExecutorError("GitHub base-branch freshness could not be verified") from exc
        if current_sha != expected_sha:
            raise ExecutorError(
                "The GitHub source branch moved while Amosclaud was working; create a fresh plan."
            )

    @staticmethod
    def _push_branch(repo: Repo, token: str, branch: str) -> None:
        try:
            with authenticated_git(repo, token):
                repo.remote("origin").push(
                    refspec=f"refs/heads/{branch}:refs/heads/{branch}",
                )
        except GitCommandError as exc:
            raise ExecutorError(
                (
                    "GitHub rejected the verified branch push; check repository "
                    "permissions or refresh the plan."
                )
            ) from exc

    def _create_pull_request(
        self,
        target: RepositoryTarget,
        branch: str,
        base: str,
        objective: str,
        runtime_result: Any,
        *,
        title: str | None,
        body: str | None,
        draft: bool,
    ) -> str:
        if not target.github_full_name or not target.github_token:
            raise ExecutorError("The GitHub target is missing its connected repository credential")
        clean_title = " ".join((title or "").split())[:200]
        if not clean_title:
            clean_title = f"Amosclaud: {objective}"[:200]
        evidence_lines = [
            (
                f"- `{check.get('name')}`: "
                f"{'passed' if check.get('passed') else 'failed'} — "
                f"{check.get('summary', '')}"
            )
            for check in runtime_result.checks
        ]
        default_body = (
            "## Amosclaud executor\n\n"
            f"Objective: {objective}\n\n"
            "This pull request was created only after a verified commit. "
            "Amosclaud does not merge pull requests.\n\n"
            "### Changed files\n"
            + "\n".join(f"- `{path}`" for path in runtime_result.changed_files)
            + "\n\n### Verification\n"
            + ("\n".join(evidence_lines) or "- No check details were returned.")
        )
        clean_body = body.strip() if body and body.strip() else default_body
        url = f"https://api.github.com/repos/{target.github_full_name}/pulls"
        try:
            with httpx.Client(timeout=self.github_timeout_seconds) as client:
                response = client.post(
                    url,
                    headers=_github_headers(target.github_token),
                    json={
                        "title": clean_title,
                        "head": branch,
                        "base": base,
                        "body": clean_body[:60_000],
                        "draft": bool(draft),
                    },
                )
        except httpx.HTTPError as exc:
            raise ExecutorError("GitHub pull-request creation could not reach the API") from exc
        if response.status_code >= 400:
            raise ExecutorError(
                f"GitHub refused pull-request creation (HTTP {response.status_code})."
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise ExecutorError("GitHub returned an invalid pull-request response") from exc
        pull_request_url = (
            str(payload.get("html_url") or "").strip() if isinstance(payload, dict) else ""
        )
        if not pull_request_url:
            raise ExecutorError("GitHub pull-request response did not include a URL")
        return pull_request_url

    def _inspect(self, target: RepositoryTarget, source_branch: str) -> tuple[list[str], list[str]]:
        blockers: list[str] = []
        evidence = [f"Target selected: {target.name}"]
        if target.is_github:
            evidence.append(f"GitHub delivery target: {target.github_full_name}")

        if target.workspace is None:
            evidence.append("Execution will use a fresh ephemeral GitHub clone.")
            return blockers, evidence
        if not target.workspace.is_dir():
            return ["The selected repository workspace does not exist."], evidence
        try:
            repo = Repo(target.workspace)
        except (InvalidGitRepositoryError, OSError) as exc:
            return [
                f"The selected workspace is not a Git repository: {type(exc).__name__}."
            ], evidence

        heads = {head.name for head in repo.heads}
        if source_branch not in heads:
            blockers.append(
                f"Source branch '{source_branch}' does not exist in the selected repository."
            )
        else:
            evidence.append(f"Source branch: {source_branch}")
            evidence.append(f"Source commit: {repo.commit(source_branch).hexsha}")
        if not target.is_github and repo.is_dirty(untracked_files=True):
            blockers.append(
                "The native repository has uncommitted changes; clean it before execution."
            )

        visible_files = []
        for path in sorted(target.workspace.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(target.workspace)
            if any(part in _SKIP_PARTS or part.startswith(".env") for part in relative.parts):
                continue
            visible_files.append(relative.as_posix())
            if len(visible_files) >= 200:
                break
        evidence.append(
            f"Inspectable repository files: {len(visible_files)} shown (bounded at 200)."
        )
        return blockers, evidence

    def _from_runtime(
        self,
        runtime_result: Any,
        target: RepositoryTarget,
        objective: str,
        record: _PlanRecord,
        *,
        delivery: str,
    ) -> ExecutionResult:
        blockers = []
        if getattr(runtime_result, "blocker", None):
            blockers.append(str(runtime_result.blocker))
        succeeded = bool(getattr(runtime_result, "succeeded", False))
        return ExecutionResult(
            run_id="exec_" + uuid.uuid4().hex,
            status="completed" if succeeded else "failed",
            summary=(
                "Verified repository change committed."
                if succeeded
                else "Execution stopped before a verified commit."
            ),
            objective=objective,
            target=target.name,
            source_branch=record.source_branch,
            plan_id=record.plan_id,
            plan=list(record.plan),
            changed_files=list(getattr(runtime_result, "changed_files", []) or []),
            checks=list(getattr(runtime_result, "checks", []) or []),
            evidence=list(getattr(runtime_result, "evidence", []) or []),
            blockers=blockers,
            branch=getattr(runtime_result, "branch", None),
            commit=getattr(runtime_result, "commit", None),
            model=dict(getattr(runtime_result, "model", {}) or {}),
            delivery=delivery,
        )

    def _model_description(self) -> dict[str, Any]:
        describe = getattr(self.model, "describe", None)
        value = describe() if callable(describe) else None
        return dict(value) if isinstance(value, dict) else {"mode": type(self.model).__name__}

    @staticmethod
    def _blocked(
        objective: str,
        target: RepositoryTarget,
        source_branch: str,
        blocker: str,
        *,
        plan: list[str] | None = None,
        plan_id: str | None = None,
    ) -> ExecutionResult:
        return ExecutionResult(
            run_id="blocked_" + uuid.uuid4().hex,
            status="blocked",
            summary="Execution was blocked before repository changes.",
            objective=objective,
            target=target.name,
            source_branch=source_branch,
            plan_id=plan_id,
            plan=plan or [],
            blockers=[blocker],
            evidence=["No repository files were changed.", f"Blocker: {blocker}"],
        )

    @staticmethod
    def _failed(
        objective: str,
        target: RepositoryTarget,
        source_branch: str,
        record: _PlanRecord,
        blocker: str,
    ) -> ExecutionResult:
        return ExecutionResult(
            run_id="failed_" + uuid.uuid4().hex,
            status="failed",
            summary="Execution stopped before a verified commit.",
            objective=objective,
            target=target.name,
            source_branch=source_branch,
            plan_id=record.plan_id,
            plan=list(record.plan),
            blockers=[blocker],
            evidence=[f"Blocker: {blocker}"],
        )


def _clean_objective(value: str) -> str:
    clean = " ".join((value or "").strip().split())
    if not clean:
        raise ValueError("An execution objective is required")
    return clean


def _validate_branch(value: str) -> str:
    clean = " ".join((value or "").strip().split())
    if not clean or not _BRANCH_RE.fullmatch(clean) or ".." in clean:
        raise ValueError("A valid source branch is required")
    return clean


def _json_payload(raw: Any) -> Any:
    text = str(raw or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return None


def _github_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


__all__ = [
    "ExecutionResult",
    "ExecutorError",
    "ExecutorService",
    "GatewayCodingModel",
    "MemoryPlanStore",
    "PlanStore",
    "RepositoryTarget",
    "SQLitePlanStore",
]

"""Amosclaud repository orchestrator and self-healing command entry point.

The root command coordinates repository guardrails with the shared Amosclaud
platform database.  A run may be attached to a native repository, pull request,
and CI pipeline so the gateway, Autonomous Agent, repository UI, and verifier
all observe one authoritative job state.
"""

from __future__ import annotations

import argparse
import datetime
import logging
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path

from amoscloud_ai.main import create_app
from database.models import AutonomousJob, AutonomousJobStatus, CIPipeline, CIStatus
from database.session import create_database, session_scope

# Export the real platform application for ``uvicorn main:app`` and ``--serve``.
app = create_app()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] Amosclaud-System: %(message)s",
)
logger = logging.getLogger("AmosclaudOrchestrator")


class AmosclaudEngine:
    """Coordinate analysis, repair, verification, and persisted job evidence."""

    def __init__(
        self,
        *,
        task_id: str | None = None,
        repository_id: int | None = None,
        pull_request_id: int | None = None,
        ci_pipeline_id: int | None = None,
    ) -> None:
        self.agent_ai = "Amosclaud-ai"
        self.agent_fixer = "Amosclaud-fixer"
        self.task_id = task_id or f"guardrail-{uuid.uuid4().hex[:16]}"
        self.repository_id = repository_id
        self.pull_request_id = pull_request_id
        self.ci_pipeline_id = ci_pipeline_id
        self.changed_files: set[str] = set()
        create_database()
        self._ensure_job()

    @property
    def database_tracking_enabled(self) -> bool:
        return self.repository_id is not None

    def _ensure_job(self) -> None:
        """Create one shared Autonomous job when a repository ID is supplied."""
        if not self.database_tracking_enabled:
            logger.info(
                "No repository ID supplied; running locally without a persisted Autonomous job."
            )
            return

        with session_scope() as session:
            job = session.query(AutonomousJob).filter_by(task_id=self.task_id).one_or_none()
            if job is None:
                job = AutonomousJob(
                    task_id=self.task_id,
                    agent_type="amosclaud-root-orchestrator",
                    repository_id=self.repository_id,
                    pull_request_id=self.pull_request_id,
                    ci_pipeline_id=self.ci_pipeline_id,
                    objective="Inspect, repair, and verify the repository guardrail failures.",
                    status=AutonomousJobStatus.QUEUED,
                )
                session.add(job)

    def _record_state(
        self,
        status: AutonomousJobStatus,
        *,
        summary: str | None = None,
        error_context: str | None = None,
        ci_status: CIStatus | None = None,
        verification_id: str | None = None,
    ) -> None:
        """Persist job and CI state without inventing success evidence."""
        if not self.database_tracking_enabled:
            return

        with session_scope() as session:
            job = session.query(AutonomousJob).filter_by(task_id=self.task_id).one()
            job.status = status
            if summary is not None:
                job.result_summary = summary
            if error_context is not None:
                job.error_context = error_context[-50_000:]

            pipeline_id = self.ci_pipeline_id or job.ci_pipeline_id
            if pipeline_id is not None and ci_status is not None:
                pipeline = session.get(CIPipeline, pipeline_id)
                if pipeline is not None:
                    pipeline.status = ci_status
                    pipeline.execution_logs = (error_context or summary or "")[-100_000:]
                    if ci_status in {CIStatus.PASSED, CIStatus.FAILED}:
                        pipeline.completed_at = datetime.datetime.now(datetime.timezone.utc)
                    if ci_status == CIStatus.PASSED:
                        pipeline.verification_id = verification_id

    @staticmethod
    def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(command, capture_output=True, text=True, check=False)

    def run_guardrails(self) -> bool:
        """Inspect the repository, attempt bounded repairs, and persist evidence."""
        logger.info("[%s] Running strict Python guardrails.", self.agent_ai)
        self._record_state(
            AutonomousJobStatus.INSPECTING,
            summary="Repository guardrail inspection started.",
            ci_status=CIStatus.RUNNING,
        )

        result = self._run(
            [
                "flake8",
                ".",
                "--count",
                "--select=E9,F63,F7,F82",
                "--show-source",
                "--statistics",
            ]
        )
        evidence = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()

        if result.returncode == 0:
            verification_id = f"verification-{uuid.uuid4().hex}"
            self._record_state(
                AutonomousJobStatus.PASSED,
                summary="Guardrail verification passed without requiring a repair.",
                ci_status=CIStatus.PASSED,
                verification_id=verification_id,
            )
            logger.info("[%s] Code passes guardrail verification.", self.agent_ai)
            return True

        logger.warning("[%s] Guardrail failures detected.", self.agent_ai)
        if evidence:
            print(evidence)
        self._record_state(
            AutonomousJobStatus.REPAIRING,
            summary="Guardrail failures detected; bounded repair started.",
            error_context=evidence,
            ci_status=CIStatus.RUNNING,
        )
        return self.auto_heal(evidence)

    def auto_heal(self, log_output: str) -> bool:
        """Apply only recognized deterministic repairs, then verify again."""
        logger.info("[%s] Activating bounded deterministic repair.", self.agent_fixer)
        error_pattern = re.compile(r"^(?P<path>.+?\.py):(?P<line>\d+):(?P<column>\d+):")

        fixed_any = False
        for output_line in log_output.splitlines():
            match = error_pattern.match(output_line.strip())
            if match is None:
                continue
            file_path = Path(match.group("path"))
            line_number = int(match.group("line"))
            if file_path.is_file() and self.fix_syntax_anomaly(file_path, line_number, output_line):
                self.changed_files.add(str(file_path))
                fixed_any = True

        if not fixed_any:
            message = "No recognized safe deterministic repair matched the reported failures."
            logger.error("[%s] %s", self.agent_fixer, message)
            self._record_state(
                AutonomousJobStatus.FAILED,
                summary=message,
                error_context=log_output,
                ci_status=CIStatus.FAILED,
            )
            return False

        self._record_state(
            AutonomousJobStatus.VERIFYING,
            summary=f"Verifying changes in {len(self.changed_files)} file(s).",
            ci_status=CIStatus.RUNNING,
        )
        final_check = self._run(["flake8", ".", "--count", "--select=E9,F63,F7,F82"])
        final_evidence = "\n".join(
            part for part in (final_check.stdout, final_check.stderr) if part
        ).strip()

        if final_check.returncode != 0:
            self._record_state(
                AutonomousJobStatus.FAILED,
                summary="The repair was applied, but verification still failed.",
                error_context=final_evidence,
                ci_status=CIStatus.FAILED,
            )
            return False

        verification_id = f"verification-{uuid.uuid4().hex}"
        self._record_state(
            AutonomousJobStatus.PASSED,
            summary=(
                "Verified deterministic repair completed for: "
                + ", ".join(sorted(self.changed_files))
            ),
            error_context=final_evidence,
            ci_status=CIStatus.PASSED,
            verification_id=verification_id,
        )
        logger.info("[%s] Repair passed verification.", self.agent_fixer)

        if os.getenv("AMOSCLAUD_ALLOW_GIT_PUSH", "").lower() in {"1", "true", "yes"}:
            self.commit_and_push_patch()
        else:
            logger.info(
                "Verified files remain on the current branch for native Amosclaud review; "
                "automatic Git push is disabled."
            )
        return True

    def fix_syntax_anomaly(
        self,
        file_path: Path,
        line_no: int,
        error_msg: str,
    ) -> bool:
        """Repair a small allow-list of unambiguous generated-code mistakes."""
        del error_msg
        lines = file_path.read_text(encoding="utf-8").splitlines(keepends=True)
        index = line_no - 1
        if index < 0 or index >= len(lines):
            return False
        target_line = lines[index]

        if "BaseModel" in target_line and "from pydantic import BaseModel" not in "".join(lines):
            lines.insert(0, "from pydantic import BaseModel\n")
        elif "app.post" in target_line and "app = FastAPI" not in "".join(lines):
            lines.insert(0, "from fastapi import FastAPI\napp = FastAPI()\n")
        else:
            # Multiline signatures and brackets require parser-aware repair. Do not
            # append punctuation based on one line because that can corrupt valid code.
            return False

        file_path.write_text("".join(lines), encoding="utf-8")
        return True

    def commit_and_push_patch(self) -> None:
        """Optionally publish only files changed by this verified repair."""
        if not self.changed_files:
            return
        try:
            subprocess.run(
                ["git", "config", "user.name", "Amosclaud-fixer"], check=True
            )
            subprocess.run(
                ["git", "config", "user.email", "fixer@amosclaud.internal"], check=True
            )
            subprocess.run(["git", "add", "--", *sorted(self.changed_files)], check=True)
            subprocess.run(
                ["git", "commit", "-m", "chore: apply verified Amosclaud repair"],
                check=True,
            )
            branch = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            subprocess.run(["git", "push", "origin", branch], check=True)
        except subprocess.CalledProcessError as exc:
            logger.error("Verified repair could not be published: %s", exc)

    @staticmethod
    def serve() -> None:
        """Start the real Amosclaud platform application."""
        import uvicorn

        uvicorn.run("main:app", host="0.0.0.0", port=8000)


def main() -> None:
    parser = argparse.ArgumentParser(description="Amosclaud Autonomous repository orchestrator")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--test-guardrails", action="store_true")
    group.add_argument("--serve", action="store_true")
    parser.add_argument("--task-id")
    parser.add_argument("--repository-id", type=int)
    parser.add_argument("--pull-request-id", type=int)
    parser.add_argument("--ci-pipeline-id", type=int)
    args = parser.parse_args()

    engine = AmosclaudEngine(
        task_id=args.task_id,
        repository_id=args.repository_id,
        pull_request_id=args.pull_request_id,
        ci_pipeline_id=args.ci_pipeline_id,
    )
    if args.test_guardrails:
        sys.exit(0 if engine.run_guardrails() else 1)
    engine.serve()


if __name__ == "__main__":
    main()

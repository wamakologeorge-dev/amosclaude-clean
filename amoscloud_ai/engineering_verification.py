from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class EngineeringVerification:
    """Run bounded engineering checks and retain truthful evidence reports."""

    REPORT_SCHEMA = "amosclaud.engineering-verification.v1"
    MAX_OUTPUT = 12_000

    def __init__(
        self,
        repository_root: Path | None = None,
        report_root: Path | None = None,
    ) -> None:
        self.repository_root = (
            repository_root or Path(__file__).resolve().parent.parent
        ).resolve()
        configured = os.getenv("AMOSCLAUD_VERIFICATION_DIR", "").strip()
        default_root = self.repository_root / "data" / "engineering-verification"
        selected_root = report_root or (Path(configured) if configured else default_root)
        self.report_root = selected_root.resolve()
        self.report_root.mkdir(parents=True, exist_ok=True)

    def _run(
        self,
        name: str,
        command: list[str],
        timeout: int,
    ) -> dict[str, Any]:
        started = time.monotonic()
        try:
            process = subprocess.run(
                command,
                cwd=self.repository_root,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )
            output = ((process.stdout or "") + (process.stderr or ""))[
                -self.MAX_OUTPUT :
            ]
            return {
                "name": name,
                "status": "passed" if process.returncode == 0 else "failed",
                "exit_code": process.returncode,
                "duration_seconds": round(time.monotonic() - started, 3),
                "output": self._redact(output),
            }
        except subprocess.TimeoutExpired as exc:
            captured = "".join(
                part for part in (exc.stdout, exc.stderr) if isinstance(part, str)
            )
            output = (captured + f"\nTimed out after {timeout} seconds")[
                -self.MAX_OUTPUT :
            ]
            return {
                "name": name,
                "status": "failed",
                "exit_code": None,
                "duration_seconds": round(time.monotonic() - started, 3),
                "output": self._redact(output),
            }
        except OSError as exc:
            return {
                "name": name,
                "status": "failed",
                "exit_code": None,
                "duration_seconds": round(time.monotonic() - started, 3),
                "output": (
                    "Unable to start verification command: "
                    f"{type(exc).__name__}"
                ),
            }

    @staticmethod
    def _redact(value: str) -> str:
        value = re.sub(
            r"(?i)(token|secret|password|api[_-]?key)\s*[=:]\s*\S+",
            r"\1=[REDACTED]",
            value,
        )
        return re.sub(
            r"(?i)bearer\s+[A-Za-z0-9._~-]+",
            "Bearer [REDACTED]",
            value,
        )

    def _git(self, *args: str) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=self.repository_root,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        return result.stdout.strip() if result.returncode == 0 else ""

    def current_commit(self) -> str:
        return self._git("rev-parse", "HEAD") or "unknown"

    def run(self) -> dict[str, Any]:
        verification_id = str(uuid.uuid4())
        commit_sha = self.current_commit()
        checks = [
            self._run(
                "python-compile",
                [sys.executable, "-m", "compileall", "-q", "amoscloud_ai"],
                180,
            ),
            self._run(
                "focused-server-contract",
                [
                    sys.executable,
                    "-m",
                    "amoscloud_ai.amos_test_language",
                    "tests/server.focus.amos",
                ],
                180,
            ),
            self._run(
                "test-suite",
                [sys.executable, "-m", "pytest", "-q"],
                900,
            ),
        ]
        status = (
            "verified"
            if checks and all(item["status"] == "passed" for item in checks)
            else "failed"
        )
        report = {
            "schema": self.REPORT_SCHEMA,
            "verification_id": verification_id,
            "status": status,
            "commit_sha": commit_sha,
            "branch": self._git("branch", "--show-current") or "detached",
            "repository_clean": not bool(self._git("status", "--porcelain")),
            "checks": checks,
            "summary": {
                "passed": sum(item["status"] == "passed" for item in checks),
                "failed": sum(item["status"] == "failed" for item in checks),
                "total": len(checks),
            },
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        timestamp = report["generated_at"].replace(":", "-")
        destination = self.report_root / f"{timestamp}-{commit_sha[:12]}.json"
        temporary = destination.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(report, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temporary.replace(destination)
        report["report_file"] = destination.name
        return report

    def reports(self, limit: int = 50) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        paths = sorted(self.report_root.glob("*.json"), reverse=True)
        for path in paths[: max(1, min(limit, 200))]:
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
                item["report_file"] = path.name
                result.append(item)
            except (OSError, json.JSONDecodeError):
                continue
        return result

    def latest_for_commit(self, commit_sha: str) -> dict[str, Any] | None:
        for report in self.reports(200):
            if report.get("commit_sha") == commit_sha:
                return report
        return None

    def merge_results(self, limit: int = 100) -> list[dict[str, Any]]:
        format_string = "%H%x1f%P%x1f%aI%x1f%s"
        bounded_limit = max(1, min(limit, 500))
        raw = self._git(
            "log",
            "--first-parent",
            f"--max-count={bounded_limit}",
            f"--pretty=format:{format_string}",
        )
        results: list[dict[str, Any]] = []
        for line in raw.splitlines():
            fields = line.split("\x1f", 3)
            if len(fields) != 4:
                continue
            commit_sha, parents, authored_at, title = fields
            files_raw = self._git(
                "diff-tree",
                "--root",
                "--no-commit-id",
                "--name-only",
                "-r",
                commit_sha,
            )
            files = [item for item in files_raw.splitlines() if item]
            match = re.search(r"\(#(\d+)\)", title)
            report = self.latest_for_commit(commit_sha)
            results.append(
                {
                    "commit_sha": commit_sha,
                    "short_sha": commit_sha[:12],
                    "title": title,
                    "merged_at": authored_at,
                    "parent_count": len(parents.split()) if parents else 0,
                    "pull_request": int(match.group(1)) if match else None,
                    "files_changed": len(files),
                    "files": files[:100],
                    "verification_status": (
                        report.get("status")
                        if report
                        else "historical-unverified"
                    ),
                    "verification_id": (
                        report.get("verification_id") if report else None
                    ),
                    "verification_report": (
                        report.get("report_file") if report else None
                    ),
                }
            )
        return results


def verification_contract(
    *,
    engineering: bool,
    report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the evidence contract used by agent completion responses."""
    if not engineering:
        return {
            "required": False,
            "status": "not-applicable",
            "verified": False,
        }
    if not report:
        return {"required": True, "status": "pending", "verified": False}
    verified = report.get("status") == "verified"
    return {
        "required": True,
        "status": report.get("status", "failed"),
        "verified": verified,
        "verification_id": report.get("verification_id"),
        "commit_sha": report.get("commit_sha"),
    }

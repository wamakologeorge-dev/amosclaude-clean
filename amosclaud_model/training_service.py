"""Protected background training jobs and dataset-rights validation."""

from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from amosclaud_model.model import FolderLanguageModel

DEFAULT_ALLOWED_LICENSES = {
    "apache-2.0",
    "bsd-2-clause",
    "bsd-3-clause",
    "cc0-1.0",
    "mit",
    "project-owned",
    "amosclaud project-owned",
    "amosclaud-contributor-license-1.0",
    "amosclaud-commercial-dataset-license-1.0",
    "commercial-license",
}


def audit_dataset_licenses(root: Path) -> dict[str, Any]:
    """Verify that imported datasets have an explicitly approved rights label."""
    manifest = root / "datasets" / "manifest.jsonl"
    allowed = DEFAULT_ALLOWED_LICENSES | {
        item.strip().lower()
        for item in os.getenv("AMOSCLAUD_TRAINING_LICENSE_ALLOWLIST", "").split(",")
        if item.strip()
    }
    records: list[dict[str, Any]] = []
    invalid: list[dict[str, str]] = []
    if manifest.exists():
        for number, line in enumerate(manifest.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                invalid.append({"record": str(number), "reason": "invalid JSON"})
                continue
            records.append(record)
            license_name = str(record.get("license", "")).strip().lower()
            if license_name not in allowed:
                invalid.append(
                    {
                        "record": str(record.get("id") or number),
                        "dataset": str(record.get("dataset", "unknown")),
                        "license": license_name or "missing",
                        "reason": "license is not approved for training",
                    }
                )
    return {
        "approved": bool(records) and not invalid,
        "datasets": len(records),
        "invalid": invalid,
        "allowed_licenses": sorted(allowed),
    }


class TrainingService:
    """Single-writer job service that keeps model training state in its folder."""

    def __init__(self, root: Path):
        self.root = root
        self.jobs = root / "training" / "jobs"
        self.jobs.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._active: str | None = None
        self._recover_interrupted_jobs()

    def submit(self, operation: str = "train") -> dict[str, Any]:
        if operation not in {"train", "evaluate"}:
            raise ValueError("Unsupported training operation")
        audit = audit_dataset_licenses(self.root)
        if operation == "train" and not audit["approved"]:
            raise ValueError("Dataset license audit failed; review datasets/manifest.jsonl")
        with self._lock:
            if self._active:
                raise RuntimeError(f"Training job {self._active} is already running")
            job_id = "train_" + uuid.uuid4().hex
            job = {
                "id": job_id,
                "operation": operation,
                "status": "queued",
                "created_at": self._now(),
                "started_at": None,
                "finished_at": None,
                "license_audit": audit,
                "result": None,
                "error": None,
            }
            self._write(job)
            self._active = job_id
            threading.Thread(target=self._run, args=(job_id,), daemon=True).start()
            return job

    def get(self, job_id: str) -> dict[str, Any] | None:
        if not job_id.startswith("train_"):
            return None
        path = self.jobs / f"{job_id}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def list(self, limit: int = 25) -> list[dict[str, Any]]:
        values = [
            json.loads(path.read_text(encoding="utf-8")) for path in self.jobs.glob("train_*.json")
        ]
        return sorted(values, key=lambda item: item["created_at"], reverse=True)[
            : max(1, min(limit, 100))
        ]

    def _run(self, job_id: str) -> None:
        job = self.get(job_id)
        if not job:
            return
        job.update(status="running", started_at=self._now())
        self._write(job)
        try:
            model = FolderLanguageModel(self.root)
            result = model.train() if job["operation"] == "train" else model.evaluate()
            if result is None:
                raise ValueError("No evaluation documents found under datasets/eval")
            job.update(status="completed", result=result)
        except Exception as error:
            job.update(
                status="failed", error={"type": type(error).__name__, "message": str(error)[:500]}
            )
        finally:
            job["finished_at"] = self._now()
            self._write(job)
            with self._lock:
                self._active = None

    def _write(self, job: dict[str, Any]) -> None:
        path = self.jobs / f"{job['id']}.json"
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(job, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, path)

    def _recover_interrupted_jobs(self) -> None:
        for path in self.jobs.glob("train_*.json"):
            job = json.loads(path.read_text(encoding="utf-8"))
            if job.get("status") in {"queued", "running"}:
                job.update(
                    status="failed",
                    finished_at=self._now(),
                    error={"type": "ServiceRestart", "message": "Training service restarted"},
                )
                self._write(job)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

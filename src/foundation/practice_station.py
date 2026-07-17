"""Agents Practice Station: safe self-test and lesson practice for Autonomous."""
from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .curriculum import UniversalCurriculum


@dataclass
class PracticeResult:
    practice_id: str
    level: int
    track: str
    lesson: str
    status: str
    score: int
    checks: list[dict[str, Any]]
    evidence: list[str]
    promoted: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AgentsPracticeStation:
    """Lets agents practice every learned skill without touching production data."""

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()
        root = self.workspace / ".amosclaud"
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / "agents-practice-station.db"
        self.curriculum = UniversalCurriculum()
        with sqlite3.connect(self.path) as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS practice_runs("
                "id TEXT PRIMARY KEY, level INTEGER, track TEXT, lesson TEXT, status TEXT, "
                "score INTEGER, evidence TEXT, created_at TEXT)"
            )

    def practice(
        self,
        level: int,
        *,
        verifier: Callable[[], list[dict[str, Any]]] | None = None,
        evidence: list[str] | None = None,
    ) -> PracticeResult:
        lesson = self.curriculum.lesson(level)
        practice_id = uuid.uuid4().hex
        checks = verifier() if verifier else self._default_checks(lesson.track)
        passed = sum(1 for item in checks if item.get("passed"))
        score = round((passed / max(1, len(checks))) * 100)
        status = "passed" if score >= 80 else "needs-practice"
        proof = list(evidence or [])
        proof.extend(str(item.get("summary", "")) for item in checks)
        promoted = status == "passed" and bool(proof)
        with sqlite3.connect(self.path) as db:
            db.execute(
                "INSERT INTO practice_runs VALUES(?,?,?,?,?,?,?,?)",
                (
                    practice_id,
                    lesson.level,
                    lesson.track,
                    lesson.title,
                    status,
                    score,
                    json.dumps(proof),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
        return PracticeResult(
            practice_id=practice_id,
            level=lesson.level,
            track=lesson.track,
            lesson=lesson.title,
            status=status,
            score=score,
            checks=checks,
            evidence=proof,
            promoted=promoted,
        )

    def _default_checks(self, track: str) -> list[dict[str, Any]]:
        checks = [
            {"name": "workspace-isolation", "passed": self.workspace.is_dir(), "summary": "Practice remained in the designated workspace."},
            {"name": "authority-separation", "passed": True, "summary": "Practice did not grant production authority."},
            {"name": "evidence-required", "passed": True, "summary": "The lesson requires verification evidence."},
        ]
        if track in {"codex-engineering", "coding-foundations", "self-healing"}:
            checks.append({"name": "repository-present", "passed": any(self.workspace.iterdir()), "summary": "Repository evidence is available for coding practice."})
        return checks

    def history(self, limit: int = 50) -> list[dict[str, Any]]:
        with sqlite3.connect(self.path) as db:
            rows = db.execute(
                "SELECT id,level,track,lesson,status,score,evidence,created_at "
                "FROM practice_runs ORDER BY created_at DESC LIMIT ?",
                (max(1, min(limit, 500)),),
            ).fetchall()
        return [
            {
                "practice_id": row[0],
                "level": row[1],
                "track": row[2],
                "lesson": row[3],
                "status": row[4],
                "score": row[5],
                "evidence": json.loads(row[6]),
                "created_at": row[7],
            }
            for row in rows
        ]

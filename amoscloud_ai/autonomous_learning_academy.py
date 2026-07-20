"""Evidence-based teacher and instructor system for Amosclaud Autonomous.

The academy gives every agent one shared path for learning from verified platform
incidents, successful repairs, tests, reviews, and approved architecture rules.
It never trains a model directly and never allows unverified output to become a
lesson.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


AGENT_ROLES = {
    1: "receive-and-understand",
    2: "perceive-repository-evidence",
    3: "plan-with-model",
    4: "act-when-authorized",
    5: "verify-and-report",
}

TRUSTED_SOURCES = {
    "verified-fix",
    "passing-test",
    "approved-review",
    "approved-architecture",
    "trusted-documentation",
    "runtime-evidence",
}


@dataclass(frozen=True)
class LessonCandidate:
    title: str
    problem_signature: str
    root_cause: str
    resolution: str
    verification: str
    source_type: str
    source_reference: str
    target_agents: tuple[int, ...] = (1, 2, 3, 4, 5)
    tags: tuple[str, ...] = ()


class AcademyError(RuntimeError):
    pass


class AutonomousLearningAcademy:
    """Single teacher path used by the Autonomous orchestrator and all agents."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        configured = db_path or os.getenv("AMOSCLAUD_ACADEMY_DB", "/data/autonomous-academy.db")
        self.db_path = Path(configured)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.db_path)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        return db

    def _initialize(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS academy_lessons (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fingerprint TEXT NOT NULL UNIQUE,
                    title TEXT NOT NULL,
                    problem_signature TEXT NOT NULL,
                    root_cause TEXT NOT NULL,
                    resolution TEXT NOT NULL,
                    verification TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_reference TEXT NOT NULL,
                    target_agents TEXT NOT NULL,
                    tags TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('candidate','approved','rejected')),
                    created_at TEXT NOT NULL,
                    approved_at TEXT
                );
                CREATE TABLE IF NOT EXISTS academy_progress (
                    agent_id INTEGER NOT NULL,
                    lesson_id INTEGER NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('assigned','completed','failed')),
                    score INTEGER NOT NULL DEFAULT 0,
                    evidence TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(agent_id, lesson_id),
                    FOREIGN KEY(lesson_id) REFERENCES academy_lessons(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS academy_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    lesson_id INTEGER,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(lesson_id) REFERENCES academy_lessons(id) ON DELETE SET NULL
                );
                """
            )
            db.commit()

    @staticmethod
    def _fingerprint(candidate: LessonCandidate) -> str:
        normalized = "\n".join(
            [
                candidate.problem_signature.strip().lower(),
                candidate.root_cause.strip().lower(),
                candidate.resolution.strip().lower(),
                candidate.verification.strip().lower(),
            ]
        )
        return hashlib.sha256(normalized.encode()).hexdigest()

    @staticmethod
    def _validate(candidate: LessonCandidate) -> None:
        if candidate.source_type not in TRUSTED_SOURCES:
            raise AcademyError("Lesson source is not trusted")
        if not candidate.source_reference.strip():
            raise AcademyError("Lesson requires a source reference")
        if not candidate.verification.strip():
            raise AcademyError("Lesson requires verification evidence")
        if not candidate.root_cause.strip() or not candidate.resolution.strip():
            raise AcademyError("Lesson requires a root cause and resolution")
        invalid_agents = set(candidate.target_agents) - set(AGENT_ROLES)
        if invalid_agents:
            raise AcademyError(f"Unknown target agents: {sorted(invalid_agents)}")

    def submit_verified_lesson(self, candidate: LessonCandidate, *, auto_approve: bool = False) -> dict:
        """Record a lesson once evidence exists; duplicates collapse to one lesson."""
        self._validate(candidate)
        fingerprint = self._fingerprint(candidate)
        now = datetime.now(timezone.utc).isoformat()
        status = "approved" if auto_approve else "candidate"
        approved_at = now if auto_approve else None
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO academy_lessons(
                    fingerprint,title,problem_signature,root_cause,resolution,
                    verification,source_type,source_reference,target_agents,tags,
                    status,created_at,approved_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(fingerprint) DO UPDATE SET
                    verification=excluded.verification,
                    source_reference=excluded.source_reference,
                    tags=excluded.tags
                """,
                (
                    fingerprint,
                    candidate.title.strip(),
                    candidate.problem_signature.strip(),
                    candidate.root_cause.strip(),
                    candidate.resolution.strip(),
                    candidate.verification.strip(),
                    candidate.source_type,
                    candidate.source_reference.strip(),
                    json.dumps(sorted(set(candidate.target_agents))),
                    json.dumps(sorted(set(candidate.tags))),
                    status,
                    now,
                    approved_at,
                ),
            )
            row = db.execute("SELECT * FROM academy_lessons WHERE fingerprint=?", (fingerprint,)).fetchone()
            self._event(db, "lesson-submitted", int(row["id"]), {"status": row["status"]})
            db.commit()
        return self._serialize_lesson(row)

    def approve_lesson(self, lesson_id: int, *, evidence: str) -> dict:
        if not evidence.strip():
            raise AcademyError("Approval requires evidence")
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as db:
            row = db.execute("SELECT * FROM academy_lessons WHERE id=?", (lesson_id,)).fetchone()
            if not row:
                raise AcademyError("Lesson not found")
            db.execute(
                "UPDATE academy_lessons SET status='approved',approved_at=? WHERE id=?",
                (now, lesson_id),
            )
            for agent_id in json.loads(row["target_agents"]):
                db.execute(
                    """
                    INSERT INTO academy_progress(agent_id,lesson_id,status,score,evidence,updated_at)
                    VALUES(?,?,'assigned',0,?,?)
                    ON CONFLICT(agent_id,lesson_id) DO UPDATE SET status='assigned',evidence=excluded.evidence,updated_at=excluded.updated_at
                    """,
                    (agent_id, lesson_id, evidence.strip(), now),
                )
            self._event(db, "lesson-approved", lesson_id, {"evidence": evidence.strip()})
            db.commit()
            updated = db.execute("SELECT * FROM academy_lessons WHERE id=?", (lesson_id,)).fetchone()
        return self._serialize_lesson(updated)

    def lesson_for_issue(self, problem_text: str, *, agent_id: int | None = None, limit: int = 5) -> list[dict]:
        """Return approved lessons relevant to a new issue using deterministic terms."""
        terms = {term.lower() for term in problem_text.replace("/", " ").replace("_", " ").split() if len(term) >= 4}
        with self._connect() as db:
            rows = db.execute("SELECT * FROM academy_lessons WHERE status='approved' ORDER BY approved_at DESC").fetchall()
        ranked: list[tuple[int, sqlite3.Row]] = []
        for row in rows:
            targets = set(json.loads(row["target_agents"]))
            if agent_id is not None and agent_id not in targets:
                continue
            haystack = " ".join(
                [row["title"], row["problem_signature"], row["root_cause"], row["resolution"], row["tags"]]
            ).lower()
            score = sum(1 for term in terms if term in haystack)
            if score:
                ranked.append((score, row))
        ranked.sort(key=lambda item: (-item[0], -int(item[1]["id"])))
        return [self._serialize_lesson(row) | {"match_score": score} for score, row in ranked[:limit]]

    def complete_lesson(self, agent_id: int, lesson_id: int, *, score: int, evidence: str) -> dict:
        if agent_id not in AGENT_ROLES:
            raise AcademyError("Unknown agent")
        if not 0 <= score <= 100:
            raise AcademyError("Score must be between 0 and 100")
        if not evidence.strip():
            raise AcademyError("Completion requires evidence")
        status = "completed" if score >= 80 else "failed"
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as db:
            lesson = db.execute("SELECT 1 FROM academy_lessons WHERE id=? AND status='approved'", (lesson_id,)).fetchone()
            if not lesson:
                raise AcademyError("Approved lesson not found")
            db.execute(
                """
                INSERT INTO academy_progress(agent_id,lesson_id,status,score,evidence,updated_at)
                VALUES(?,?,?,?,?,?)
                ON CONFLICT(agent_id,lesson_id) DO UPDATE SET status=excluded.status,score=excluded.score,evidence=excluded.evidence,updated_at=excluded.updated_at
                """,
                (agent_id, lesson_id, status, score, evidence.strip(), now),
            )
            self._event(db, "lesson-completed", lesson_id, {"agent_id": agent_id, "score": score, "status": status})
            db.commit()
        return {"agent_id": agent_id, "agent_role": AGENT_ROLES[agent_id], "lesson_id": lesson_id, "status": status, "score": score}

    def classroom_status(self) -> dict:
        with self._connect() as db:
            lesson_counts = {row["status"]: row["count"] for row in db.execute("SELECT status,COUNT(*) AS count FROM academy_lessons GROUP BY status")}
            progress = db.execute(
                "SELECT agent_id,status,COUNT(*) AS count,COALESCE(AVG(score),0) AS average_score FROM academy_progress GROUP BY agent_id,status"
            ).fetchall()
        agents = {agent_id: {"role": role, "assigned": 0, "completed": 0, "failed": 0, "average_score": 0.0} for agent_id, role in AGENT_ROLES.items()}
        for row in progress:
            entry = agents[int(row["agent_id"])]
            entry[row["status"]] = int(row["count"])
            entry["average_score"] = round(float(row["average_score"]), 2)
        return {
            "service": "Amosclaud Autonomous Learning Academy",
            "teacher": "evidence-based-instructor",
            "lessons": {"candidate": lesson_counts.get("candidate", 0), "approved": lesson_counts.get("approved", 0), "rejected": lesson_counts.get("rejected", 0)},
            "agents": agents,
            "rules": [
                "Never learn from an unverified result",
                "Never convert secrets or personal data into lessons",
                "Never give Agent 4 write authority through a lesson",
                "Require test, review, runtime, or architecture evidence",
            ],
        }

    def build_teacher_context(self, issue: str, *, agent_id: int) -> dict:
        """Compact context the orchestrator can inject before an agent handles work."""
        return {
            "agent_id": agent_id,
            "agent_role": AGENT_ROLES.get(agent_id, "unknown"),
            "issue": issue,
            "lessons": self.lesson_for_issue(issue, agent_id=agent_id),
            "instruction": "Use relevant approved lessons as guidance, then independently verify current repository and runtime evidence.",
        }

    def _event(self, db: sqlite3.Connection, event_type: str, lesson_id: int | None, payload: dict) -> None:
        db.execute(
            "INSERT INTO academy_events(event_type,lesson_id,payload,created_at) VALUES(?,?,?,?)",
            (event_type, lesson_id, json.dumps(payload, sort_keys=True), datetime.now(timezone.utc).isoformat()),
        )

    @staticmethod
    def _serialize_lesson(row: sqlite3.Row) -> dict:
        result = dict(row)
        result["target_agents"] = json.loads(result["target_agents"])
        result["tags"] = json.loads(result["tags"])
        return result


def verified_fix_lesson(
    *,
    title: str,
    problem_signature: str,
    root_cause: str,
    resolution: str,
    tests: Iterable[str],
    source_reference: str,
    target_agents: tuple[int, ...] = (1, 2, 3, 4, 5),
    tags: tuple[str, ...] = (),
) -> LessonCandidate:
    """Convenience constructor used after a fix has passed its verification."""
    verification = "; ".join(item.strip() for item in tests if item.strip())
    return LessonCandidate(
        title=title,
        problem_signature=problem_signature,
        root_cause=root_cause,
        resolution=resolution,
        verification=verification,
        source_type="verified-fix",
        source_reference=source_reference,
        target_agents=target_agents,
        tags=tags,
    )

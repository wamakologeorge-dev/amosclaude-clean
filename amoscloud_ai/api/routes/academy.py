"""Owner-visible progress metrics for the Autonomous Learning Academy."""
from __future__ import annotations

import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from amoscloud_ai.api.routes.admin import _admin_user
from amoscloud_ai.autonomous_learning_academy import AGENT_ROLES, AutonomousLearningAcademy

router = APIRouter(prefix="/academy", tags=["autonomous-academy"])
MAX_LEVEL = 5000


def _academy() -> AutonomousLearningAcademy:
    return AutonomousLearningAcademy()


@router.get("/dashboard")
def academy_dashboard(admin=Depends(_admin_user)) -> dict:
    """Return measurable, evidence-based learning progress for the owner dashboard."""
    del admin
    academy = _academy()
    with academy._connect() as db:
        lesson_totals = db.execute(
            "SELECT status,COUNT(*) count FROM academy_lessons GROUP BY status"
        ).fetchall()
        progress_rows = db.execute(
            """
            SELECT agent_id,
                   SUM(CASE WHEN status='assigned' THEN 1 ELSE 0 END) assigned,
                   SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) completed,
                   SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) failed,
                   COALESCE(AVG(CASE WHEN status='completed' THEN score END),0) average_score,
                   COALESCE(SUM(CASE WHEN status='completed' THEN score ELSE 0 END),0) earned_points
            FROM academy_progress GROUP BY agent_id ORDER BY agent_id
            """
        ).fetchall()
        event_rows = db.execute(
            """
            SELECT substr(created_at,1,10) day,COUNT(*) events,
                   SUM(CASE WHEN event_type='lesson-completed' THEN 1 ELSE 0 END) completions
            FROM academy_events
            GROUP BY substr(created_at,1,10)
            ORDER BY day DESC LIMIT 30
            """
        ).fetchall()
        recent = db.execute(
            "SELECT event_type,lesson_id,payload,created_at FROM academy_events ORDER BY id DESC LIMIT 15"
        ).fetchall()

    counts = {row["status"]: int(row["count"]) for row in lesson_totals}
    approved = counts.get("approved", 0)
    completed = sum(int(row["completed"] or 0) for row in progress_rows)
    failed = sum(int(row["failed"] or 0) for row in progress_rows)
    score_points = sum(int(row["earned_points"] or 0) for row in progress_rows)
    learning_points = approved * 25 + score_points
    target_points = max(1, int(os.getenv("AMOSCLAUD_ACADEMY_LEVEL_5000_POINTS", "500000")))
    current_level = min(MAX_LEVEL, max(1, 1 + int((learning_points / target_points) * (MAX_LEVEL - 1))))
    level_progress = min(100.0, round((learning_points / target_points) * 100, 3))

    agents = []
    indexed = {int(row["agent_id"]): row for row in progress_rows}
    for agent_id, role in AGENT_ROLES.items():
        row = indexed.get(agent_id)
        agents.append(
            {
                "agent_id": agent_id,
                "role": role,
                "assigned": int(row["assigned"] or 0) if row else 0,
                "completed": int(row["completed"] or 0) if row else 0,
                "failed": int(row["failed"] or 0) if row else 0,
                "average_score": round(float(row["average_score"] or 0), 2) if row else 0.0,
            }
        )

    timeline = [dict(row) for row in reversed(event_rows)]
    return {
        "service": "Amosclaud Autonomous Learning Academy",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "current_level": current_level,
        "maximum_level": MAX_LEVEL,
        "learning_points": learning_points,
        "level_5000_target_points": target_points,
        "graduation_progress_percent": level_progress,
        "approved_lessons": approved,
        "candidate_lessons": counts.get("candidate", 0),
        "rejected_lessons": counts.get("rejected", 0),
        "completed_assignments": completed,
        "failed_assignments": failed,
        "agents": agents,
        "timeline": timeline,
        "recent_activity": [dict(row) for row in recent],
        "level_rule": "Levels advance only from approved lessons and evidence-backed completed lesson scores. Time alone never increases the level.",
        "authority_rule": "Learning level never grants write access or founder authority.",
    }

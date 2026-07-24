from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any

from .autonomous_brain import GitHubAutonomousBrain
from .bot import AmosclaudBot, WRITE_ASSOCIATIONS

MISSION_MARKER = "amosclaud-mission-ledger"
TASK_STATES = {"pending", "running", "blocked", "verified", "failed", "rolled_back"}
DEFAULT_BUDGETS = {
    "max_files_changed": 20,
    "max_repair_attempts": 3,
    "max_workflow_retries": 2,
    "max_tasks": 12,
}


@dataclass
class MissionTask:
    task_id: str
    title: str
    depends_on: list[str] = field(default_factory=list)
    status: str = "pending"
    evidence: list[str] = field(default_factory=list)
    blocker: str = ""
    confidence: float = 0.5

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.task_id,
            "title": self.title,
            "depends_on": self.depends_on,
            "status": self.status,
            "evidence": self.evidence,
            "blocker": self.blocker,
            "confidence": round(max(0.0, min(self.confidence, 1.0)), 2),
        }


@dataclass
class Mission:
    mission_id: str
    objective: str
    tasks: list[MissionTask]
    budgets: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_BUDGETS))
    attempts_used: int = 0
    workflow_retries_used: int = 0
    changed_files: list[str] = field(default_factory=list)
    status: str = "active"
    confidence: float = 0.5
    last_verified_task: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": 1,
            "mission_id": self.mission_id,
            "objective": self.objective,
            "status": self.status,
            "confidence": round(max(0.0, min(self.confidence, 1.0)), 2),
            "last_verified_task": self.last_verified_task,
            "budgets": self.budgets,
            "usage": {
                "repair_attempts": self.attempts_used,
                "workflow_retries": self.workflow_retries_used,
                "changed_files": self.changed_files,
            },
            "tasks": [task.to_dict() for task in self.tasks],
        }


def _task_id(index: int, title: str) -> str:
    return f"task-{index}-{sha256(title.encode()).hexdigest()[:6]}"


def build_mission(objective: str) -> Mission:
    clean = " ".join((objective or "").split())
    if not clean:
        raise ValueError("A mission objective is required")
    titles = [
        "Triage the objective and identify risk",
        "Inspect current repository evidence",
        "Build the dependency-aware implementation plan",
        "Execute authorized repository changes",
        "Run targeted tests and security checks",
        "Verify the complete repository state",
        "Publish the verified outcome and learning record",
    ]
    tasks: list[MissionTask] = []
    previous = ""
    for index, title in enumerate(titles, 1):
        task_id = _task_id(index, title)
        tasks.append(MissionTask(task_id, title, [previous] if previous else []))
        previous = task_id
    mission_id = "mission-" + sha256(clean.lower().encode()).hexdigest()[:12]
    return Mission(mission_id, clean, tasks)


def encode_mission_marker(mission: Mission) -> str:
    payload = json.dumps(mission.to_dict(), ensure_ascii=False, separators=(",", ":"))
    return f"<!-- {MISSION_MARKER}:{payload} -->"


def decode_mission_marker(body: str) -> Mission | None:
    match = re.search(rf"<!--\s*{re.escape(MISSION_MARKER)}:(\{{.*?\}})\s*-->", body or "", re.DOTALL)
    if not match:
        return None
    try:
        payload = json.loads(match.group(1))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    objective = " ".join(str(payload.get("objective") or "").split())
    mission_id = str(payload.get("mission_id") or "").strip()
    if not objective or not mission_id:
        return None
    tasks = []
    for raw in payload.get("tasks") or []:
        status = str(raw.get("status") or "pending")
        tasks.append(
            MissionTask(
                str(raw.get("id") or ""),
                str(raw.get("title") or "Untitled task"),
                [str(item) for item in raw.get("depends_on") or []],
                status if status in TASK_STATES else "pending",
                [str(item)[:500] for item in raw.get("evidence") or []],
                str(raw.get("blocker") or "")[:1000],
                float(raw.get("confidence") or 0.5),
            )
        )
    budgets = dict(DEFAULT_BUDGETS)
    budgets.update({key: int(value) for key, value in (payload.get("budgets") or {}).items() if key in budgets})
    usage = payload.get("usage") or {}
    return Mission(
        mission_id,
        objective,
        tasks,
        budgets,
        max(0, int(usage.get("repair_attempts") or 0)),
        max(0, int(usage.get("workflow_retries") or 0)),
        [str(item) for item in usage.get("changed_files") or []],
        str(payload.get("status") or "active"),
        float(payload.get("confidence") or 0.5),
        str(payload.get("last_verified_task") or ""),
    )


def latest_mission(comments: list[dict[str, Any]]) -> Mission | None:
    for comment in reversed(comments):
        mission = decode_mission_marker(str(comment.get("body") or ""))
        if mission:
            return mission
    return None


def _task(mission: Mission, task_id: str) -> MissionTask:
    for item in mission.tasks:
        if item.task_id == task_id:
            return item
    raise KeyError(f"Unknown mission task: {task_id}")


def advance_task(mission: Mission, task_id: str, evidence: str) -> Mission:
    task = _task(mission, task_id)
    proof = " ".join((evidence or "").split())
    if not proof:
        raise ValueError("Current verification evidence is required")
    if not all(_task(mission, dependency).status == "verified" for dependency in task.depends_on):
        raise ValueError("Task dependencies are not verified")
    task.status = "verified"
    task.evidence.append(proof[:500])
    task.blocker = ""
    task.confidence = max(task.confidence, 0.8)
    mission.last_verified_task = task.task_id
    verified = sum(item.status == "verified" for item in mission.tasks)
    mission.confidence = min(1.0, 0.5 + verified / max(len(mission.tasks), 1) * 0.5)
    if verified == len(mission.tasks):
        mission.status = "verified"
    return mission


def block_task(mission: Mission, task_id: str, reason: str) -> Mission:
    task = _task(mission, task_id)
    blocker = " ".join((reason or "").split())
    if not blocker:
        raise ValueError("A blocker reason is required")
    task.status = "blocked"
    task.blocker = blocker[:1000]
    task.confidence = min(task.confidence, 0.45)
    mission.status = "blocked"
    mission.confidence = min(mission.confidence, 0.55)
    return mission


def recover_mission(mission: Mission) -> Mission:
    after_checkpoint = not mission.last_verified_task
    for task in mission.tasks:
        if after_checkpoint and task.status in {"running", "blocked", "failed", "rolled_back"}:
            task.status = "pending"
            task.blocker = ""
        if task.task_id == mission.last_verified_task:
            after_checkpoint = True
    mission.status = "active"
    return mission


def render_mission(mission: Mission, brain: dict[str, Any] | None = None) -> str:
    verified = sum(task.status == "verified" for task in mission.tasks)
    progress = round(verified / max(len(mission.tasks), 1) * 100)
    icons = {"pending": "⬜", "running": "🟨", "blocked": "🟥", "verified": "🟩", "failed": "🟥", "rolled_back": "↩️"}
    lines = [
        "### Amosclaud — Multi-Task Mission Ledger", "",
        f"**Mission:** `{mission.mission_id}`", f"**Objective:** {mission.objective}",
        f"**Status:** `{mission.status.upper()}`", f"**Progress:** `{progress}%`",
        f"**Confidence:** `{mission.confidence:.2f}`",
        f"**Last verified checkpoint:** `{mission.last_verified_task or 'none'}`", "",
        "## Tasks and dependencies", "", "| Task | State | Depends on | Evidence / blocker |", "|---|---|---|---|",
    ]
    for task in mission.tasks:
        evidence = task.evidence[-1] if task.evidence else task.blocker or "none"
        safe_evidence = evidence.replace("|", "\\|")
        depends = ", ".join(task.depends_on) or "none"
        lines.append(f"| `{task.task_id}` {task.title} | {icons[task.status]} `{task.status}` | `{depends}` | {safe_evidence} |")
    lines.extend([
        "", "## Execution budget",
        f"- Files changed: `{len(mission.changed_files)}/{mission.budgets['max_files_changed']}`",
        f"- Repair attempts: `{mission.attempts_used}/{mission.budgets['max_repair_attempts']}`",
        f"- Workflow retries: `{mission.workflow_retries_used}/{mission.budgets['max_workflow_retries']}`",
    ])
    if brain:
        missing = (brain.get("rollimage") or {}).get("unknowns") or []
        lines.extend([
            "", "## Decision evidence",
            f"- Proven memories: `{len(brain.get('proven_memories', []))}`",
            f"- Failed approaches to avoid: `{len(brain.get('failed_attempts_to_avoid', []))}`",
            f"- Approved lessons: `{len(brain.get('approved_lessons', []))}`",
            f"- Missing evidence: {', '.join(missing) or 'none recorded'}",
        ])
    lines.extend([
        "",
        "Trusted collaborators can use `@amosclaud mission advance <task-id> <verification evidence>`, "
        "`@amosclaud mission block <task-id> <reason>`, or `@amosclaud mission recover`.",
        "A task cannot be verified until its dependencies and current evidence are verified.",
        encode_mission_marker(mission),
    ])
    return "\n".join(lines)[:12000]


def parse_mission_request(text: str) -> tuple[str | None, str, str]:
    normalized = " ".join((text or "").strip().split())
    lowered = normalized.lower()
    name = next((item for item in ("@amosclaud-bot", "@amosclaud") if lowered.startswith(item)), None)
    if not name:
        return None, "", ""
    remainder = normalized[len(name):].strip()
    command, _, rest = remainder.partition(" ")
    if command.lower() not in {"mission", "goal"}:
        return None, "", ""
    action, _, value = rest.strip().partition(" ")
    if action.lower() in {"show", "status", "recover"}:
        return action.lower(), "", value.strip()
    if action.lower() in {"advance", "block"}:
        task_id, _, detail = value.strip().partition(" ")
        return action.lower(), task_id, detail.strip()
    return ("start", "", rest.strip()) if rest.strip() else ("show", "", "")


def handle_mission_request(bot: AmosclaudBot, payload: dict[str, Any]) -> int | None:
    comment = payload.get("comment") or {}
    action, task_id, detail = parse_mission_request(str(comment.get("body") or ""))
    if not action:
        return None
    issue = payload.get("issue") or {}
    number = issue.get("number")
    if not isinstance(number, int):
        return 0
    comments = bot._request("GET", f"/repos/{bot.repository}/issues/{number}/comments?per_page=100")
    mission = latest_mission(comments if isinstance(comments, list) else [])
    association = str(comment.get("author_association") or "NONE").upper()
    if action == "start":
        mission = build_mission(detail)
    elif mission is None:
        bot.post_comment(number, "### Amosclaud — No active mission\nStart one with `@amosclaud mission <objective>`. ")
        return 0
    elif action in {"advance", "block", "recover"} and association not in WRITE_ASSOCIATIONS:
        bot.post_comment(number, "### Amosclaud — Mission update blocked\nOnly OWNER, MEMBER, or COLLABORATOR may change mission state.")
        return 0
    elif action == "advance":
        try:
            mission = advance_task(mission, task_id, detail)
        except (KeyError, ValueError) as exc:
            bot.post_comment(number, f"### Amosclaud — Mission update rejected\n{exc}")
            return 0
    elif action == "block":
        try:
            mission = block_task(mission, task_id, detail)
        except (KeyError, ValueError) as exc:
            bot.post_comment(number, f"### Amosclaud — Mission update rejected\n{exc}")
            return 0
    elif action == "recover":
        mission = recover_mission(mission)
    brain = GitHubAutonomousBrain(bot.workspace, bot.repository).prepare("goal", mission.objective)
    bot.post_comment(number, render_mission(mission, brain))
    return 0

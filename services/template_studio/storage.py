"""SQLite persistence for Template Studio plans, tasks and versions."""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

from .policy import clean_metadata, clean_progress, clean_status


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class PlanStore:
    def __init__(self, path: Path) -> None:
        self.path = path.expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS plans (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    owner TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'draft',
                    progress INTEGER NOT NULL DEFAULT 0,
                    content TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS plan_versions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    plan_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(plan_id) REFERENCES plans(id) ON DELETE CASCADE,
                    UNIQUE(plan_id, version)
                );
                CREATE TABLE IF NOT EXISTS plan_tasks (
                    id TEXT PRIMARY KEY,
                    plan_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'todo',
                    priority TEXT NOT NULL DEFAULT 'medium',
                    due_date TEXT,
                    position INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(plan_id) REFERENCES plans(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_plans_updated_at ON plans(updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_versions_plan ON plan_versions(plan_id, version DESC);
                CREATE INDEX IF NOT EXISTS idx_tasks_plan ON plan_tasks(plan_id, position, created_at);
                """
            )

    @staticmethod
    def _plan(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"], "title": row["title"], "kind": row["kind"],
            "owner": row["owner"], "status": row["status"],
            "progress": int(row["progress"]), "content": row["content"],
            "metadata": json.loads(row["metadata_json"] or "{}"),
            "created_at": row["created_at"], "updated_at": row["updated_at"],
        }

    @staticmethod
    def _task(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"], "plan_id": row["plan_id"], "title": row["title"],
            "status": row["status"], "priority": row["priority"],
            "due_date": row["due_date"], "position": int(row["position"]),
            "created_at": row["created_at"], "updated_at": row["updated_at"],
        }

    def create_plan(self, payload: dict[str, Any]) -> dict[str, Any]:
        plan_id, now = str(uuid.uuid4()), utc_now()
        metadata = clean_metadata(payload.get("metadata"))
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO plans
                   (id,title,kind,owner,status,progress,content,metadata_json,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (plan_id, payload["title"], payload["kind"], str(payload.get("owner", ""))[:160],
                 clean_status(payload.get("status", "draft")), clean_progress(payload.get("progress", 0)),
                 payload.get("content", ""), json.dumps(metadata, ensure_ascii=False), now, now),
            )
        self.snapshot(plan_id, reason="created")
        plan = self.get_plan(plan_id)
        assert plan is not None
        return plan

    def list_plans(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM plans ORDER BY updated_at DESC LIMIT ?", (max(1, min(int(limit), 500)),)).fetchall()
        return [self._plan(row) for row in rows]

    def get_plan(self, plan_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM plans WHERE id = ?", (plan_id,)).fetchone()
        return self._plan(row) if row else None

    def update_plan(self, plan_id: str, changes: dict[str, Any]) -> dict[str, Any] | None:
        allowed = {"title", "kind", "owner", "status", "progress", "content", "metadata"}
        updates = {key: value for key, value in changes.items() if key in allowed}
        if not updates:
            return self.get_plan(plan_id)
        columns: list[str] = []
        values: list[Any] = []
        for key, value in updates.items():
            if key == "metadata":
                columns.append("metadata_json = ?"); values.append(json.dumps(clean_metadata(value), ensure_ascii=False))
            elif key == "status":
                columns.append("status = ?"); values.append(clean_status(value))
            elif key == "progress":
                columns.append("progress = ?"); values.append(clean_progress(value))
            elif key == "owner":
                columns.append("owner = ?"); values.append(str(value or "")[:160])
            else:
                columns.append(f"{key} = ?"); values.append(value)
        columns.append("updated_at = ?"); values.extend([utc_now(), plan_id])
        with self._connect() as connection:
            cursor = connection.execute(f"UPDATE plans SET {', '.join(columns)} WHERE id = ?", values)
            if cursor.rowcount == 0:
                return None
        return self.get_plan(plan_id)

    def delete_plan(self, plan_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute("DELETE FROM plans WHERE id = ?", (plan_id,))
        return cursor.rowcount > 0

    def snapshot(self, plan_id: str, *, reason: str = "manual") -> dict[str, Any] | None:
        plan = self.get_plan(plan_id)
        if plan is None:
            return None
        with self._connect() as connection:
            row = connection.execute("SELECT COALESCE(MAX(version),0) value FROM plan_versions WHERE plan_id = ?", (plan_id,)).fetchone()
            version = int(row["value"]) + 1
            metadata = dict(plan["metadata"]); metadata["snapshot_reason"] = str(reason)[:80]
            connection.execute("INSERT INTO plan_versions (plan_id,version,content,metadata_json,created_at) VALUES (?,?,?,?,?)", (plan_id, version, plan["content"], json.dumps(metadata, ensure_ascii=False), utc_now()))
        return {"plan_id": plan_id, "version": version, "reason": reason}

    def list_versions(self, plan_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute("SELECT id,plan_id,version,metadata_json,created_at FROM plan_versions WHERE plan_id = ? ORDER BY version DESC LIMIT ?", (plan_id, max(1, min(int(limit), 200)))).fetchall()
        return [{"id": int(row["id"]), "plan_id": row["plan_id"], "version": int(row["version"]), "metadata": json.loads(row["metadata_json"] or "{}"), "created_at": row["created_at"]} for row in rows]

    def get_version(self, plan_id: str, version: int) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM plan_versions WHERE plan_id = ? AND version = ?", (plan_id, int(version))).fetchone()
        if not row:
            return None
        return {"id": int(row["id"]), "plan_id": row["plan_id"], "version": int(row["version"]), "content": row["content"], "metadata": json.loads(row["metadata_json"] or "{}"), "created_at": row["created_at"]}

    def restore_version(self, plan_id: str, version: int) -> dict[str, Any] | None:
        selected = self.get_version(plan_id, version)
        if selected is None:
            return None
        self.snapshot(plan_id, reason=f"before_restore_{version}")
        return self.update_plan(plan_id, {"content": selected["content"]})

    def create_task(self, plan_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        if self.get_plan(plan_id) is None:
            return None
        title = " ".join(str(payload.get("title", "")).split())[:200]
        if not title:
            raise ValueError("Task title is required")
        status = str(payload.get("status", "todo")).lower()
        priority = str(payload.get("priority", "medium")).lower()
        if status not in {"todo", "doing", "blocked", "done"}:
            raise ValueError("Unsupported task status")
        if priority not in {"low", "medium", "high", "critical"}:
            raise ValueError("Unsupported task priority")
        task_id, now = str(uuid.uuid4()), utc_now()
        with self._connect() as connection:
            connection.execute("INSERT INTO plan_tasks (id,plan_id,title,status,priority,due_date,position,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)", (task_id, plan_id, title, status, priority, str(payload.get("due_date") or "")[:40] or None, max(0, int(payload.get("position", 0))), now, now))
        self._sync_task_progress(plan_id)
        return self.get_task(task_id)

    def list_tasks(self, plan_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM plan_tasks WHERE plan_id = ? ORDER BY position,created_at", (plan_id,)).fetchall()
        return [self._task(row) for row in rows]

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM plan_tasks WHERE id = ?", (task_id,)).fetchone()
        return self._task(row) if row else None

    def update_task(self, task_id: str, changes: dict[str, Any]) -> dict[str, Any] | None:
        current = self.get_task(task_id)
        if current is None:
            return None
        allowed = {"title", "status", "priority", "due_date", "position"}
        updates = {key: value for key, value in changes.items() if key in allowed}
        if not updates:
            return current
        if "title" in updates:
            updates["title"] = " ".join(str(updates["title"]).split())[:200]
            if not updates["title"]: raise ValueError("Task title is required")
        if "status" in updates:
            updates["status"] = str(updates["status"]).lower()
            if updates["status"] not in {"todo", "doing", "blocked", "done"}: raise ValueError("Unsupported task status")
        if "priority" in updates:
            updates["priority"] = str(updates["priority"]).lower()
            if updates["priority"] not in {"low", "medium", "high", "critical"}: raise ValueError("Unsupported task priority")
        if "position" in updates: updates["position"] = max(0, int(updates["position"]))
        if "due_date" in updates: updates["due_date"] = str(updates["due_date"] or "")[:40] or None
        columns = [f"{key} = ?" for key in updates]; values = list(updates.values())
        columns.append("updated_at = ?"); values.extend([utc_now(), task_id])
        with self._connect() as connection:
            connection.execute(f"UPDATE plan_tasks SET {', '.join(columns)} WHERE id = ?", values)
        self._sync_task_progress(current["plan_id"])
        return self.get_task(task_id)

    def delete_task(self, task_id: str) -> bool:
        current = self.get_task(task_id)
        if current is None:
            return False
        with self._connect() as connection:
            connection.execute("DELETE FROM plan_tasks WHERE id = ?", (task_id,))
        self._sync_task_progress(current["plan_id"])
        return True

    def _sync_task_progress(self, plan_id: str) -> None:
        tasks = self.list_tasks(plan_id)
        if tasks:
            self.update_plan(plan_id, {"progress": round(sum(task["status"] == "done" for task in tasks) * 100 / len(tasks))})

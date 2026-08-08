"""Shared execution-node, Java-pod, resource-lease, and PipeFail runtime.

The module is mounted beneath the existing cooperation router. It deliberately
uses the same database, pipeline IDs, events, artifacts, ownership rules, and
approval model so a Java runtime cannot become a second platform.
"""

from __future__ import annotations

import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from amoscloud_ai.api.routes import pipeline_cooperation as cooperation

router = APIRouter(tags=["pipeline-runtime"])
_LOCK = threading.RLock()
JAVA_IMAGE = os.getenv("AMOSCLAUD_JAVA_POD_IMAGE", "amosclaud-java-pod:21")
NodeStatus = Literal["ready", "busy", "draining", "offline"]


class NodeCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    endpoint: str | None = Field(default=None, max_length=2_000)
    capabilities: list[str] = Field(..., min_length=1, max_length=100)
    cpu_millis: int = Field(default=2_000, ge=100, le=1_000_000)
    memory_mb: int = Field(default=4_096, ge=256, le=4_194_304)
    disk_mb: int = Field(default=20_480, ge=512, le=100_000_000)
    gpu_units: int = Field(default=0, ge=0, le=1_000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class NodeHeartbeat(BaseModel):
    status: NodeStatus = "ready"
    metadata: dict[str, Any] = Field(default_factory=dict)


class JavaPodCreate(BaseModel):
    jdk: Literal["17", "21", "25"] = "21"
    build_tool: Literal["auto", "maven", "gradle", "javac"] = "auto"
    cpu_millis: int = Field(default=1_000, ge=100, le=64_000)
    memory_mb: int = Field(default=2_048, ge=256, le=262_144)
    disk_mb: int = Field(default=4_096, ge=512, le=10_000_000)
    gpu_units: int = Field(default=0, ge=0, le=64)
    network: Literal["none", "restricted", "egress"] = "restricted"
    command: str | None = Field(default=None, max_length=4_000)
    max_attempts: int = Field(default=3, ge=1, le=10)
    metadata: dict[str, Any] = Field(default_factory=dict)


class JavaPodStart(BaseModel):
    runtime_id: str | None = Field(default=None, max_length=500)


class JavaPodComplete(BaseModel):
    summary: str = Field(..., min_length=1, max_length=20_000)
    artifacts: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    metrics: dict[str, Any] = Field(default_factory=dict)


class JavaPodFailure(BaseModel):
    error: str = Field(..., min_length=1, max_length=20_000)
    kind: Literal[
        "startup",
        "compile",
        "test",
        "timeout",
        "out_of_memory",
        "node_unreachable",
        "policy",
        "unknown",
    ] = "unknown"
    retryable: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _user(amos_session: str | None = Cookie(default=None)) -> sqlite3.Row:
    return cooperation._current_user(amos_session)


def _db() -> sqlite3.Connection:
    db = cooperation._db()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS cooperation_nodes (
            id TEXT PRIMARY KEY,user_id INTEGER NOT NULL,name TEXT NOT NULL,
            endpoint TEXT,status TEXT NOT NULL,capabilities_json TEXT NOT NULL,
            cpu_millis INTEGER NOT NULL,memory_mb INTEGER NOT NULL,
            disk_mb INTEGER NOT NULL,gpu_units INTEGER NOT NULL DEFAULT 0,
            metadata_json TEXT NOT NULL DEFAULT '{}',created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,last_heartbeat TEXT NOT NULL,
            UNIQUE(user_id,name)
        );
        CREATE INDEX IF NOT EXISTS idx_cooperation_nodes
            ON cooperation_nodes(user_id,status,last_heartbeat DESC);
        CREATE TABLE IF NOT EXISTS cooperation_java_pods (
            id TEXT PRIMARY KEY,pipeline_id TEXT NOT NULL,user_id INTEGER NOT NULL,
            node_id TEXT,lease_id TEXT,state TEXT NOT NULL,image TEXT NOT NULL,
            jdk TEXT NOT NULL,build_tool TEXT NOT NULL,network TEXT NOT NULL,
            command TEXT,attempt INTEGER NOT NULL DEFAULT 1,
            max_attempts INTEGER NOT NULL DEFAULT 3,runtime_id TEXT,
            resources_json TEXT NOT NULL,metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,updated_at TEXT NOT NULL,started_at TEXT,
            finished_at TEXT,error_detail TEXT NOT NULL DEFAULT '',
            FOREIGN KEY(pipeline_id) REFERENCES cooperation_pipeline_runs(id)
                ON DELETE CASCADE,
            FOREIGN KEY(node_id) REFERENCES cooperation_nodes(id) ON DELETE SET NULL
        );
        CREATE INDEX IF NOT EXISTS idx_cooperation_java_pods
            ON cooperation_java_pods(pipeline_id,created_at DESC);
        CREATE TABLE IF NOT EXISTS cooperation_resource_leases (
            id TEXT PRIMARY KEY,pipeline_id TEXT NOT NULL,pod_id TEXT NOT NULL,
            node_id TEXT NOT NULL,user_id INTEGER NOT NULL,state TEXT NOT NULL,
            resources_json TEXT NOT NULL,created_at TEXT NOT NULL,released_at TEXT,
            release_reason TEXT NOT NULL DEFAULT '',
            FOREIGN KEY(pipeline_id) REFERENCES cooperation_pipeline_runs(id)
                ON DELETE CASCADE,
            FOREIGN KEY(pod_id) REFERENCES cooperation_java_pods(id) ON DELETE CASCADE,
            FOREIGN KEY(node_id) REFERENCES cooperation_nodes(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_cooperation_resource_leases
            ON cooperation_resource_leases(node_id,state,created_at);
        CREATE TABLE IF NOT EXISTS cooperation_pipefail (
            id TEXT PRIMARY KEY,pipeline_id TEXT NOT NULL,pod_id TEXT NOT NULL,
            node_id TEXT,user_id INTEGER NOT NULL,kind TEXT NOT NULL,
            retryable INTEGER NOT NULL,action TEXT NOT NULL,error_detail TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}',created_at TEXT NOT NULL,
            FOREIGN KEY(pipeline_id) REFERENCES cooperation_pipeline_runs(id)
                ON DELETE CASCADE,
            FOREIGN KEY(pod_id) REFERENCES cooperation_java_pods(id) ON DELETE CASCADE
        );
        """)
    db.commit()
    return db


def _row(db: sqlite3.Connection, table: str, item_id: str, user: sqlite3.Row) -> sqlite3.Row:
    allowed = {"cooperation_nodes", "cooperation_java_pods", "cooperation_resource_leases"}
    if table not in allowed:
        raise RuntimeError("Unsupported runtime table")
    clause = "id=?" if cooperation._is_admin(user) else "id=? AND user_id=?"
    values = (item_id,) if cooperation._is_admin(user) else (item_id, int(user["id"]))
    item = db.execute(f"SELECT * FROM {table} WHERE {clause}", values).fetchone()
    if not item:
        raise HTTPException(status_code=404, detail="Runtime resource not found")
    return item


def _usage(db: sqlite3.Connection, node_id: str) -> dict[str, int]:
    leases = db.execute(
        """SELECT resources_json FROM cooperation_resource_leases
           WHERE node_id=? AND state='active'""",
        (node_id,),
    ).fetchall()
    total = {"cpu_millis": 0, "memory_mb": 0, "disk_mb": 0, "gpu_units": 0}
    for lease in leases:
        for key, value in cooperation._loads(lease["resources_json"], {}).items():
            if key in total:
                total[key] += int(value)
    return total


def _node_json(db: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    used = _usage(db, row["id"])
    total = {key: int(row[key]) for key in used}
    available = {key: max(total[key] - used[key], 0) for key in total}
    return {
        "id": row["id"],
        "name": row["name"],
        "endpoint": row["endpoint"],
        "status": row["status"],
        "capabilities": cooperation._loads(row["capabilities_json"], []),
        "resources": {"total": total, "used": used, "available": available},
        "metadata": cooperation._loads(row["metadata_json"], {}),
        "last_heartbeat": row["last_heartbeat"],
    }


def _lease_json(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if not row:
        return None
    return {
        "id": row["id"],
        "node_id": row["node_id"],
        "state": row["state"],
        "resources": cooperation._loads(row["resources_json"], {}),
        "created_at": row["created_at"],
        "released_at": row["released_at"],
        "release_reason": row["release_reason"],
    }


def _pod_json(db: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    node = db.execute("SELECT * FROM cooperation_nodes WHERE id=?", (row["node_id"],)).fetchone()
    lease = db.execute(
        "SELECT * FROM cooperation_resource_leases WHERE id=?", (row["lease_id"],)
    ).fetchone()
    return {
        "id": row["id"],
        "pipeline_id": row["pipeline_id"],
        "state": row["state"],
        "node": _node_json(db, node) if node else None,
        "lease": _lease_json(lease),
        "image": row["image"],
        "jdk": row["jdk"],
        "build_tool": row["build_tool"],
        "network": row["network"],
        "command": row["command"],
        "attempt": row["attempt"],
        "max_attempts": row["max_attempts"],
        "runtime_id": row["runtime_id"],
        "resources": cooperation._loads(row["resources_json"], {}),
        "metadata": cooperation._loads(row["metadata_json"], {}),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "error_detail": row["error_detail"],
    }


def _select_node(
    db: sqlite3.Connection,
    user_id: int,
    request: JavaPodCreate,
    exclude: str | None = None,
) -> sqlite3.Row | None:
    wanted = {
        "cpu_millis": request.cpu_millis,
        "memory_mb": request.memory_mb,
        "disk_mb": request.disk_mb,
        "gpu_units": request.gpu_units,
    }
    candidates = []
    rows = db.execute(
        """SELECT * FROM cooperation_nodes WHERE user_id=?
           AND status IN ('ready','busy') ORDER BY last_heartbeat DESC""",
        (user_id,),
    ).fetchall()
    for node in rows:
        if node["id"] == exclude:
            continue
        capabilities = set(cooperation._loads(node["capabilities_json"], []))
        if not ({"java", "java-pod"} & capabilities):
            continue
        if request.build_tool != "auto" and request.build_tool not in capabilities:
            continue
        used = _usage(db, node["id"])
        if all(int(node[key]) - used[key] >= wanted[key] for key in wanted):
            candidates.append((-(int(node["cpu_millis"]) - used["cpu_millis"]), node["name"], node))
    return sorted(candidates, key=lambda item: (item[0], item[1]))[0][2] if candidates else None


def _lease(
    db: sqlite3.Connection,
    pipeline_id: str,
    pod_id: str,
    node_id: str,
    user_id: int,
    resources: dict[str, int],
) -> sqlite3.Row:
    lease_id = f"lease_{uuid.uuid4().hex}"
    db.execute(
        """INSERT INTO cooperation_resource_leases(
            id,pipeline_id,pod_id,node_id,user_id,state,resources_json,created_at
        ) VALUES (?,?,?,?,?,'active',?,?)""",
        (lease_id, pipeline_id, pod_id, node_id, user_id, cooperation._json(resources), _now()),
    )
    return db.execute(
        "SELECT * FROM cooperation_resource_leases WHERE id=?", (lease_id,)
    ).fetchone()


def _release(db: sqlite3.Connection, lease_id: str | None, reason: str) -> None:
    if lease_id:
        db.execute(
            """UPDATE cooperation_resource_leases SET state='released',released_at=?,
               release_reason=? WHERE id=? AND state='active'""",
            (_now(), reason[:2_000], lease_id),
        )


def _store_pod_artifacts(
    db: sqlite3.Connection,
    pod: sqlite3.Row,
    artifacts: list[dict[str, Any]],
) -> None:
    for artifact in artifacts:
        uri = str(artifact.get("uri") or "")[:4_000]
        if not uri:
            continue
        metadata = {**(artifact.get("metadata") or {}), "java_pod_id": pod["id"]}
        db.execute(
            """INSERT INTO cooperation_artifacts(
                id,pipeline_id,task_id,user_id,kind,name,uri,sha256,
                metadata_json,created_at
            ) VALUES (?,?,NULL,?,?,?,?,?,?,?)""",
            (
                f"artifact_{uuid.uuid4().hex}",
                pod["pipeline_id"],
                int(pod["user_id"]),
                str(artifact.get("kind") or "java-build")[:100],
                str(artifact.get("name") or "java-artifact")[:500],
                uri,
                str(artifact.get("sha256") or "")[:200] or None,
                cooperation._json(metadata),
                _now(),
            ),
        )


def _emit(db: sqlite3.Connection, pod: sqlite3.Row, event: str, payload: dict[str, Any]) -> None:
    cooperation._event(
        db,
        pipeline_id=pod["pipeline_id"],
        user_id=int(pod["user_id"]),
        event_type=event,
        payload={"java_pod_id": pod["id"], **payload},
    )


def _recover(db: sqlite3.Connection, pod: sqlite3.Row, failure: JavaPodFailure) -> str:
    _release(db, pod["lease_id"], f"PipeFail: {failure.kind}")
    request_data = cooperation._loads(pod["resources_json"], {})
    request = JavaPodCreate(
        jdk=pod["jdk"],
        build_tool=pod["build_tool"],
        network=pod["network"],
        command=pod["command"],
        max_attempts=int(pod["max_attempts"]),
        **request_data,
    )
    action = "failed"
    node = None
    if failure.retryable and int(pod["attempt"]) < int(pod["max_attempts"]):
        node = _select_node(db, int(pod["user_id"]), request, exclude=pod["node_id"])
        node = node or _select_node(db, int(pod["user_id"]), request)
        action = "retry_reassigned" if node else "waiting_for_node"
    now = _now()
    if node:
        lease = _lease(
            db, pod["pipeline_id"], pod["id"], node["id"], int(pod["user_id"]), request_data
        )
        db.execute(
            """UPDATE cooperation_java_pods SET node_id=?,lease_id=?,state='scheduled',
               attempt=attempt+1,runtime_id=NULL,updated_at=?,started_at=NULL,
               finished_at=NULL,error_detail=? WHERE id=?""",
            (node["id"], lease["id"], now, failure.error.strip(), pod["id"]),
        )
    else:
        state = "waiting_for_node" if action == "waiting_for_node" else "failed"
        db.execute(
            """UPDATE cooperation_java_pods SET node_id=NULL,lease_id=NULL,state=?,
               updated_at=?,finished_at=?,error_detail=? WHERE id=?""",
            (state, now, now if state == "failed" else None, failure.error.strip(), pod["id"]),
        )
    db.execute(
        """INSERT INTO cooperation_pipefail(
            id,pipeline_id,pod_id,node_id,user_id,kind,retryable,action,error_detail,
            metadata_json,created_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (
            f"pipefail_{uuid.uuid4().hex}",
            pod["pipeline_id"],
            pod["id"],
            pod["node_id"],
            pod["user_id"],
            failure.kind,
            int(failure.retryable),
            action,
            failure.error.strip(),
            cooperation._json(failure.metadata),
            now,
        ),
    )
    _emit(db, pod, f"pipefail.{action}", {"kind": failure.kind, "error": failure.error.strip()})
    return action


@router.get("/overview")
def overview(user: sqlite3.Row = Depends(_user)) -> dict[str, Any]:
    with _db() as db:
        nodes = db.execute(
            "SELECT status,COUNT(*) count FROM cooperation_nodes WHERE user_id=? GROUP BY status",
            (int(user["id"]),),
        ).fetchall()
        pods = db.execute(
            """SELECT state,COUNT(*) count FROM cooperation_java_pods
               WHERE user_id=? GROUP BY state""",
            (int(user["id"]),),
        ).fetchall()
        leases = db.execute(
            """SELECT COUNT(*) FROM cooperation_resource_leases
               WHERE user_id=? AND state='active'""",
            (int(user["id"]),),
        ).fetchone()[0]
    return {
        "runtime": "Amosclaud Java Pod Runtime",
        "nodes": {row["status"]: row["count"] for row in nodes},
        "java_pods": {row["state"]: row["count"] for row in pods},
        "active_resource_leases": leases,
    }


@router.post("/nodes", status_code=201)
def create_node(body: NodeCreate, user: sqlite3.Row = Depends(_user)) -> dict[str, Any]:
    capabilities = sorted({item.strip() for item in body.capabilities if item.strip()})
    if not ({"java", "java-pod"} & set(capabilities)):
        raise HTTPException(status_code=422, detail="Node requires java or java-pod capability")
    node_id, now = f"node_{uuid.uuid4().hex}", _now()
    with _LOCK, _db() as db:
        try:
            db.execute(
                """INSERT INTO cooperation_nodes(
                    id,user_id,name,endpoint,status,capabilities_json,cpu_millis,
                    memory_mb,disk_mb,gpu_units,metadata_json,created_at,updated_at,
                    last_heartbeat
                ) VALUES (?,?,?,?,'ready',?,?,?,?,?,?,?,?,?)""",
                (
                    node_id,
                    int(user["id"]),
                    body.name.strip(),
                    body.endpoint,
                    cooperation._json(capabilities),
                    body.cpu_millis,
                    body.memory_mb,
                    body.disk_mb,
                    body.gpu_units,
                    cooperation._json(body.metadata),
                    now,
                    now,
                    now,
                ),
            )
            db.commit()
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="Node name already exists") from exc
        return _node_json(db, _row(db, "cooperation_nodes", node_id, user))


@router.get("/nodes")
def list_nodes(user: sqlite3.Row = Depends(_user)) -> dict[str, Any]:
    with _db() as db:
        rows = db.execute(
            "SELECT * FROM cooperation_nodes WHERE user_id=? ORDER BY name",
            (int(user["id"]),),
        ).fetchall()
        return {"items": [_node_json(db, row) for row in rows]}


@router.post("/nodes/{node_id}/heartbeat")
def heartbeat_node(
    node_id: str, body: NodeHeartbeat, user: sqlite3.Row = Depends(_user)
) -> dict[str, Any]:
    with _LOCK, _db() as db:
        db.execute("BEGIN IMMEDIATE")
        node = _row(db, "cooperation_nodes", node_id, user)
        metadata = {**cooperation._loads(node["metadata_json"], {}), **body.metadata}
        now = _now()
        db.execute(
            """UPDATE cooperation_nodes SET status=?,metadata_json=?,updated_at=?,
               last_heartbeat=? WHERE id=?""",
            (body.status, cooperation._json(metadata), now, now, node_id),
        )
        if body.status == "offline":
            pods = db.execute(
                """SELECT * FROM cooperation_java_pods WHERE node_id=?
                   AND state IN ('scheduled','running')""",
                (node_id,),
            ).fetchall()
            for pod in pods:
                _recover(
                    db,
                    pod,
                    JavaPodFailure(
                        error="Execution node reported offline",
                        kind="node_unreachable",
                        retryable=True,
                        metadata={"node_id": node_id},
                    ),
                )
        db.commit()
        return _node_json(db, _row(db, "cooperation_nodes", node_id, user))


@router.post("/pipelines/{pipeline_id}/java-pods", status_code=201)
def create_java_pod(
    pipeline_id: str, body: JavaPodCreate, user: sqlite3.Row = Depends(_user)
) -> dict[str, Any]:
    user_id, resources = int(user["id"]), {
        "cpu_millis": body.cpu_millis,
        "memory_mb": body.memory_mb,
        "disk_mb": body.disk_mb,
        "gpu_units": body.gpu_units,
    }
    with _LOCK, _db() as db:
        db.execute("BEGIN IMMEDIATE")
        pipeline = cooperation._pipeline_row(
            db, pipeline_id, user_id, administrator=cooperation._is_admin(user)
        )
        if pipeline["state"] in {"completed", "failed", "cancelled"}:
            raise HTTPException(status_code=409, detail="Pipeline is already finished")
        node = _select_node(db, user_id, body)
        if not node:
            raise HTTPException(status_code=409, detail="No compatible node has enough resources")
        pod_id, now = f"javapod_{uuid.uuid4().hex}", _now()
        db.execute(
            """INSERT INTO cooperation_java_pods(
                id,pipeline_id,user_id,node_id,state,image,jdk,build_tool,network,
                command,attempt,max_attempts,resources_json,metadata_json,created_at,
                updated_at
            ) VALUES (?,?,?,?,'scheduled',?,?,?,?,?,1,?,?,?,?,?)""",
            (
                pod_id,
                pipeline_id,
                user_id,
                node["id"],
                JAVA_IMAGE,
                body.jdk,
                body.build_tool,
                body.network,
                body.command,
                body.max_attempts,
                cooperation._json(resources),
                cooperation._json(body.metadata),
                now,
                now,
            ),
        )
        lease = _lease(db, pipeline_id, pod_id, node["id"], user_id, resources)
        db.execute("UPDATE cooperation_java_pods SET lease_id=? WHERE id=?", (lease["id"], pod_id))
        pod = _row(db, "cooperation_java_pods", pod_id, user)
        _emit(db, pod, "resource.lease.created", {"lease_id": lease["id"], "node_id": node["id"]})
        _emit(db, pod, "java_pod.scheduled", {"node_id": node["id"], "image": JAVA_IMAGE})
        db.commit()
        return _pod_json(db, _row(db, "cooperation_java_pods", pod_id, user))


@router.get("/pipelines/{pipeline_id}/java-pods")
def list_java_pods(
    pipeline_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    user: sqlite3.Row = Depends(_user),
) -> dict[str, Any]:
    with _db() as db:
        cooperation._pipeline_row(
            db, pipeline_id, int(user["id"]), administrator=cooperation._is_admin(user)
        )
        rows = db.execute(
            """SELECT * FROM cooperation_java_pods WHERE pipeline_id=? AND user_id=?
               ORDER BY created_at DESC LIMIT ?""",
            (pipeline_id, int(user["id"]), limit),
        ).fetchall()
        return {"items": [_pod_json(db, row) for row in rows]}


@router.get("/java-pods/{pod_id}/launch-spec")
def launch_spec(pod_id: str, user: sqlite3.Row = Depends(_user)) -> dict[str, Any]:
    with _db() as db:
        pod = _row(db, "cooperation_java_pods", pod_id, user)
        if pod["state"] != "scheduled":
            raise HTTPException(status_code=409, detail="Java pod is not scheduled")
        return {
            "java_pod_id": pod["id"],
            "pipeline_id": pod["pipeline_id"],
            "node_id": pod["node_id"],
            "image": pod["image"],
            "command": pod["command"],
            "environment": {
                "AMOSCLAUD_PIPELINE_ID": pod["pipeline_id"],
                "AMOSCLAUD_JAVA_POD_ID": pod["id"],
                "AMOSCLAUD_JDK": pod["jdk"],
                "AMOSCLAUD_BUILD_TOOL": pod["build_tool"],
            },
            "mounts": [
                {"source": "pipeline-workspace", "target": "/workspace"},
                {"source": "pipeline-artifacts", "target": "/artifacts"},
            ],
            "network": pod["network"],
            "resources": cooperation._loads(pod["resources_json"], {}),
            "security": {
                "run_as_non_root": True,
                "read_only_root_filesystem": True,
                "drop_all_capabilities": True,
                "no_new_privileges": True,
            },
        }


@router.post("/java-pods/{pod_id}/start")
def start_java_pod(
    pod_id: str, body: JavaPodStart, user: sqlite3.Row = Depends(_user)
) -> dict[str, Any]:
    with _LOCK, _db() as db:
        pod = _row(db, "cooperation_java_pods", pod_id, user)
        if pod["state"] != "scheduled":
            raise HTTPException(status_code=409, detail="Java pod is not scheduled")
        now = _now()
        db.execute(
            """UPDATE cooperation_java_pods SET state='running',runtime_id=?,
               started_at=?,updated_at=? WHERE id=?""",
            (body.runtime_id, now, now, pod_id),
        )
        _emit(db, pod, "java_pod.started", {"runtime_id": body.runtime_id})
        db.commit()
        return _pod_json(db, _row(db, "cooperation_java_pods", pod_id, user))


@router.post("/java-pods/{pod_id}/complete")
def complete_java_pod(
    pod_id: str, body: JavaPodComplete, user: sqlite3.Row = Depends(_user)
) -> dict[str, Any]:
    with _LOCK, _db() as db:
        pod = _row(db, "cooperation_java_pods", pod_id, user)
        if pod["state"] not in {"scheduled", "running"}:
            raise HTTPException(status_code=409, detail="Java pod is not active")
        _release(db, pod["lease_id"], "Java pod completed")
        now, metadata = _now(), {
            **cooperation._loads(pod["metadata_json"], {}),
            "summary": body.summary.strip(),
            "metrics": body.metrics,
        }
        db.execute(
            """UPDATE cooperation_java_pods SET state='completed',metadata_json=?,
               updated_at=?,finished_at=?,error_detail='' WHERE id=?""",
            (cooperation._json(metadata), now, now, pod_id),
        )
        _store_pod_artifacts(db, pod, body.artifacts)
        _emit(db, pod, "java_pod.completed", {"summary": body.summary.strip()})
        _emit(db, pod, "resource.lease.released", {"lease_id": pod["lease_id"]})
        db.commit()
        return _pod_json(db, _row(db, "cooperation_java_pods", pod_id, user))


@router.post("/java-pods/{pod_id}/fail")
def fail_java_pod(
    pod_id: str, body: JavaPodFailure, user: sqlite3.Row = Depends(_user)
) -> dict[str, Any]:
    with _LOCK, _db() as db:
        pod = _row(db, "cooperation_java_pods", pod_id, user)
        if pod["state"] not in {"scheduled", "running", "waiting_for_node"}:
            raise HTTPException(status_code=409, detail="Java pod is not recoverable")
        action = _recover(db, pod, body)
        db.commit()
        result = _pod_json(db, _row(db, "cooperation_java_pods", pod_id, user))
        result["pipefail_action"] = action
        return result


@router.get("/pipelines/{pipeline_id}/pipefail")
def pipefail_events(
    pipeline_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    user: sqlite3.Row = Depends(_user),
) -> dict[str, Any]:
    with _db() as db:
        cooperation._pipeline_row(
            db, pipeline_id, int(user["id"]), administrator=cooperation._is_admin(user)
        )
        rows = db.execute(
            """SELECT * FROM cooperation_pipefail WHERE pipeline_id=? AND user_id=?
               ORDER BY created_at DESC LIMIT ?""",
            (pipeline_id, int(user["id"]), limit),
        ).fetchall()
        return {
            "items": [
                {
                    "id": row["id"],
                    "java_pod_id": row["pod_id"],
                    "node_id": row["node_id"],
                    "kind": row["kind"],
                    "retryable": bool(row["retryable"]),
                    "action": row["action"],
                    "error_detail": row["error_detail"],
                    "created_at": row["created_at"],
                }
                for row in rows
            ]
        }

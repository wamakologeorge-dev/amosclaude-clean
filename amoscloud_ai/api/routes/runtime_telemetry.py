"""Telemetry layouts for node proposals and PipeFail pipeline graphics.

The module is read-only. It explains scheduler choices and converts durable
runtime records into stable JSON layouts that the Control Plane can visualize
without inventing health or failure data.
"""

from __future__ import annotations

import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from amoscloud_ai.api.routes import execution_nodes
from amoscloud_ai.api.routes import pipeline_cooperation as cooperation

router = APIRouter(tags=["pipeline-telemetry"])


class NodeProposalRequest(BaseModel):
    pipeline_id: str | None = Field(default=None, max_length=200)
    jdk: Literal["17", "21", "25"] = "21"
    build_tool: Literal["auto", "maven", "gradle", "javac"] = "auto"
    cpu_millis: int = Field(default=1_000, ge=100, le=64_000)
    memory_mb: int = Field(default=2_048, ge=256, le=262_144)
    disk_mb: int = Field(default=4_096, ge=512, le=10_000_000)
    gpu_units: int = Field(default=0, ge=0, le=64)
    stale_after_seconds: int = Field(default=300, ge=30, le=86_400)


def _user(amos_session: str | None = None) -> sqlite3.Row:
    return cooperation._current_user(amos_session)


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _heartbeat_age_seconds(value: str | None) -> int | None:
    parsed = _parse_time(value)
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return max(int((datetime.now(timezone.utc) - parsed).total_seconds()), 0)


def _resource_request(body: NodeProposalRequest) -> dict[str, int]:
    return {
        "cpu_millis": body.cpu_millis,
        "memory_mb": body.memory_mb,
        "disk_mb": body.disk_mb,
        "gpu_units": body.gpu_units,
    }


def _node_proposal(
    db: sqlite3.Connection,
    row: sqlite3.Row,
    body: NodeProposalRequest,
) -> dict[str, Any]:
    requested = _resource_request(body)
    node = execution_nodes._node_json(db, row)
    available = node["resources"]["available"]
    total = node["resources"]["total"]
    capabilities = set(node["capabilities"])
    java_capable = bool({"java", "java-pod"} & capabilities)
    tool_capable = body.build_tool == "auto" or body.build_tool in capabilities
    heartbeat_age = _heartbeat_age_seconds(node["last_heartbeat"])
    heartbeat_fresh = heartbeat_age is not None and heartbeat_age <= body.stale_after_seconds
    active_status = node["status"] in {"ready", "busy"}

    resource_fit: dict[str, dict[str, Any]] = {}
    all_resources_fit = True
    headroom_ratios: list[float] = []
    for key, wanted in requested.items():
        free = int(available.get(key, 0))
        capacity = max(int(total.get(key, 0)), 1)
        fits = free >= wanted
        all_resources_fit = all_resources_fit and fits
        remaining = max(free - wanted, 0)
        headroom_ratio = remaining / capacity
        headroom_ratios.append(headroom_ratio)
        resource_fit[key] = {
            "requested": wanted,
            "available": free,
            "remaining_after_assignment": remaining,
            "fits": fits,
            "projected_utilization_percent": round(
                min(((capacity - remaining) / capacity) * 100, 100), 2
            ),
        }

    missing_capabilities: list[str] = []
    if not java_capable:
        missing_capabilities.append("java-or-java-pod")
    if not tool_capable:
        missing_capabilities.append(body.build_tool)

    reasons: list[str] = []
    if not active_status:
        reasons.append(f"node status is {node['status']}")
    if not heartbeat_fresh:
        reasons.append("node heartbeat is stale or unavailable")
    if missing_capabilities:
        reasons.append("missing capability: " + ", ".join(missing_capabilities))
    for key, fit in resource_fit.items():
        if not fit["fits"]:
            reasons.append(f"insufficient {key}")

    eligible = active_status and heartbeat_fresh and not missing_capabilities and all_resources_fit
    status_score = 20 if node["status"] == "ready" else 12 if node["status"] == "busy" else 0
    capability_score = 20 if java_capable and tool_capable else 0
    resource_score = 50 * (sum(headroom_ratios) / len(headroom_ratios))
    heartbeat_score = 0.0
    if heartbeat_age is not None and heartbeat_fresh:
        heartbeat_score = 10 * max(1 - heartbeat_age / body.stale_after_seconds, 0)
    score = round(status_score + capability_score + resource_score + heartbeat_score, 2)

    return {
        "node_id": node["id"],
        "name": node["name"],
        "endpoint": node["endpoint"],
        "status": node["status"],
        "eligible": eligible,
        "score": score,
        "heartbeat_age_seconds": heartbeat_age,
        "heartbeat_fresh": heartbeat_fresh,
        "capability_fit": {
            "available": node["capabilities"],
            "required": ["java-or-java-pod"]
            + ([] if body.build_tool == "auto" else [body.build_tool]),
            "missing": missing_capabilities,
        },
        "resource_fit": resource_fit,
        "reasons": reasons or ["compatible, fresh, and within resource limits"],
    }


def _event_item(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "pipeline_id": row["pipeline_id"],
        "pipeline_objective": row["pipeline_objective"],
        "pipeline_state": row["pipeline_state"],
        "java_pod_id": row["pod_id"],
        "node_id": row["node_id"],
        "node_name": row["node_name"],
        "kind": row["kind"],
        "retryable": bool(row["retryable"]),
        "action": row["action"],
        "error_detail": row["error_detail"],
        "metadata": cooperation._loads(row["metadata_json"], {}),
        "created_at": row["created_at"],
    }


def _dimension(counter: Counter[str], total: int) -> list[dict[str, Any]]:
    return [
        {
            "key": key,
            "count": count,
            "percent": round((count / total) * 100, 2) if total else 0,
        }
        for key, count in sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    ]


def _timeline(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, int]] = defaultdict(
        lambda: {"total": 0, "retryable": 0, "recovered": 0, "terminal": 0}
    )
    for item in items:
        created_at = str(item["created_at"] or "")
        bucket = f"{created_at[:13]}:00:00+00:00" if len(created_at) >= 13 else "unknown"
        values = buckets[bucket]
        values["total"] += 1
        values["retryable"] += int(item["retryable"])
        values["recovered"] += int(item["action"] == "retry_reassigned")
        values["terminal"] += int(item["action"] == "failed")
    return [{"bucket": bucket, **buckets[bucket]} for bucket in sorted(buckets)]


def _pipeline_graphics(
    db: sqlite3.Connection,
    pipeline: sqlite3.Row,
    failures: list[dict[str, Any]],
) -> dict[str, Any]:
    pod_rows = db.execute(
        """SELECT state,COUNT(*) count,MAX(attempt) max_attempt
           FROM cooperation_java_pods WHERE pipeline_id=? GROUP BY state""",
        (pipeline["id"],),
    ).fetchall()
    pod_states = {row["state"]: int(row["count"]) for row in pod_rows}
    pod_total = sum(pod_states.values())
    actions = Counter(item["action"] for item in failures)
    kinds = Counter(item["kind"] for item in failures)
    recovered = actions.get("retry_reassigned", 0)
    waiting = actions.get("waiting_for_node", 0)
    terminal = actions.get("failed", 0)

    nodes = [
        {
            "key": "pipeline",
            "label": "Pipeline",
            "value": 1,
            "state": pipeline["state"],
        },
        {
            "key": "java_pods",
            "label": "Java pods",
            "value": pod_total,
            "state": "runtime",
        },
        {
            "key": "pipefail",
            "label": "PipeFail",
            "value": len(failures),
            "state": "failure",
        },
        {
            "key": "recovered",
            "label": "Reassigned",
            "value": recovered,
            "state": "recovered",
        },
        {
            "key": "waiting",
            "label": "Waiting",
            "value": waiting,
            "state": "waiting",
        },
        {
            "key": "terminal",
            "label": "Terminal",
            "value": terminal,
            "state": "terminal",
        },
    ]
    edges = [
        {"from": "pipeline", "to": "java_pods", "value": pod_total},
        {"from": "java_pods", "to": "pipefail", "value": len(failures)},
        {"from": "pipefail", "to": "recovered", "value": recovered},
        {"from": "pipefail", "to": "waiting", "value": waiting},
        {"from": "pipefail", "to": "terminal", "value": terminal},
    ]
    return {
        "layout": "amosclaud.graphics.pipefail-pipeline.v1",
        "pipeline": {
            "id": pipeline["id"],
            "objective": pipeline["objective"],
            "mode": pipeline["mode"],
            "state": pipeline["state"],
            "branch": pipeline["branch"],
        },
        "summary": {
            "java_pods": pod_total,
            "pipefail": len(failures),
            "recovered": recovered,
            "waiting_for_node": waiting,
            "terminal": terminal,
        },
        "pod_states": pod_states,
        "kind_bars": _dimension(kinds, len(failures)),
        "action_bars": _dimension(actions, len(failures)),
        "nodes": nodes,
        "edges": edges,
        "timeline": _timeline(failures),
    }


def _telemetry_layout(
    db: sqlite3.Connection,
    user_id: int,
    pipeline_id: str | None,
    limit: int,
) -> dict[str, Any]:
    clauses = ["f.user_id=?"]
    values: list[Any] = [user_id]
    if pipeline_id:
        clauses.append("f.pipeline_id=?")
        values.append(pipeline_id)
    values.append(limit)
    rows = db.execute(
        f"""SELECT f.*,p.objective pipeline_objective,p.state pipeline_state,
                   n.name node_name
            FROM cooperation_pipefail f
            JOIN cooperation_pipeline_runs p ON p.id=f.pipeline_id
            LEFT JOIN cooperation_nodes n ON n.id=f.node_id
            WHERE {' AND '.join(clauses)}
            ORDER BY f.created_at DESC LIMIT ?""",
        tuple(values),
    ).fetchall()
    items = [_event_item(row) for row in rows]
    total = len(items)
    kinds = Counter(item["kind"] for item in items)
    actions = Counter(item["action"] for item in items)
    nodes = Counter(item["node_name"] or item["node_id"] or "unassigned" for item in items)

    pipeline_ids = sorted({item["pipeline_id"] for item in items})
    if pipeline_id and pipeline_id not in pipeline_ids:
        pipeline_ids.append(pipeline_id)
    graphics: list[dict[str, Any]] = []
    pipeline_summaries: list[dict[str, Any]] = []
    for current_id in pipeline_ids:
        pipeline = db.execute(
            "SELECT * FROM cooperation_pipeline_runs WHERE id=? AND user_id=?",
            (current_id, user_id),
        ).fetchone()
        if not pipeline:
            continue
        pipeline_failures = [item for item in items if item["pipeline_id"] == current_id]
        graph = _pipeline_graphics(db, pipeline, pipeline_failures)
        graphics.append(graph)
        pipeline_summaries.append(
            {
                **graph["pipeline"],
                **graph["summary"],
                "latest_pipefail_at": (
                    pipeline_failures[0]["created_at"] if pipeline_failures else None
                ),
            }
        )

    return {
        "layout": "amosclaud.telemetry.pipefail.v1",
        "scope": {
            "type": "pipeline" if pipeline_id else "all-pipelines",
            "pipeline_id": pipeline_id,
            "limit": limit,
        },
        "summary": {
            "total": total,
            "retryable": sum(int(item["retryable"]) for item in items),
            "recovered": actions.get("retry_reassigned", 0),
            "waiting_for_node": actions.get("waiting_for_node", 0),
            "terminal": actions.get("failed", 0),
            "pipelines_affected": len({item["pipeline_id"] for item in items}),
        },
        "dimensions": {
            "kind": _dimension(kinds, total),
            "action": _dimension(actions, total),
            "node": _dimension(nodes, total),
        },
        "timeline": _timeline(items),
        "pipelines": sorted(
            pipeline_summaries,
            key=lambda item: (item["latest_pipefail_at"] or "", item["id"]),
            reverse=True,
        ),
        "graphics": graphics,
        "items": items,
    }


@router.post("/telemetry/node-proposer")
def propose_node(
    body: NodeProposalRequest,
    user: sqlite3.Row = Depends(execution_nodes._user),
) -> dict[str, Any]:
    user_id = int(user["id"])
    with execution_nodes._db() as db:
        pipeline = None
        if body.pipeline_id:
            row = cooperation._pipeline_row(
                db,
                body.pipeline_id,
                user_id,
                administrator=cooperation._is_admin(user),
            )
            pipeline = {
                "id": row["id"],
                "objective": row["objective"],
                "mode": row["mode"],
                "state": row["state"],
            }
        rows = db.execute(
            "SELECT * FROM cooperation_nodes WHERE user_id=? ORDER BY name",
            (user_id,),
        ).fetchall()
        proposals = [_node_proposal(db, row, body) for row in rows]
        proposals.sort(key=lambda item: (not item["eligible"], -item["score"], item["name"]))
        for rank, proposal in enumerate(proposals, start=1):
            proposal["rank"] = rank
            proposal["selected"] = False
        selected = next((proposal for proposal in proposals if proposal["eligible"]), None)
        if selected:
            selected["selected"] = True
        return {
            "layout": "amosclaud.telemetry.node-proposer.v1",
            "scheduler_contract": "advisory-only; pod creation revalidates capacity",
            "pipeline": pipeline,
            "request": {
                "jdk": body.jdk,
                "build_tool": body.build_tool,
                "resources": _resource_request(body),
                "stale_after_seconds": body.stale_after_seconds,
            },
            "selected_node_id": selected["node_id"] if selected else None,
            "eligible_nodes": sum(int(item["eligible"]) for item in proposals),
            "proposals": proposals,
        }


@router.get("/telemetry/pipefail")
def all_pipefail_telemetry(
    pipeline_id: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=500, ge=1, le=5_000),
    user: sqlite3.Row = Depends(execution_nodes._user),
) -> dict[str, Any]:
    user_id = int(user["id"])
    with execution_nodes._db() as db:
        if pipeline_id:
            cooperation._pipeline_row(
                db,
                pipeline_id,
                user_id,
                administrator=cooperation._is_admin(user),
            )
        return _telemetry_layout(db, user_id, pipeline_id, limit)


@router.get("/pipelines/{pipeline_id}/telemetry")
def pipeline_telemetry(
    pipeline_id: str,
    limit: int = Query(default=500, ge=1, le=5_000),
    user: sqlite3.Row = Depends(execution_nodes._user),
) -> dict[str, Any]:
    user_id = int(user["id"])
    with execution_nodes._db() as db:
        cooperation._pipeline_row(
            db,
            pipeline_id,
            user_id,
            administrator=cooperation._is_admin(user),
        )
        return _telemetry_layout(db, user_id, pipeline_id, limit)

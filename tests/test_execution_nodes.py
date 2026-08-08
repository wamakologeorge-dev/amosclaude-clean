from __future__ import annotations

from pathlib import Path

import pytest

from amoscloud_ai.api.routes import auth, execution_nodes
from amoscloud_ai.api.routes import pipeline_cooperation as cooperation


@pytest.fixture
def runtime_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    database = tmp_path / "runtime.db"
    monkeypatch.setattr(auth, "DB_PATH", database)
    return database


@pytest.fixture
def user() -> dict:
    return {"id": 71, "email": "owner@example.com", "is_admin": False}


def _pipeline(user: dict) -> dict:
    return cooperation.create_cooperation_pipeline(
        cooperation.CooperationPipelineCreate(
            objective="Compile and verify the Java service.",
            mode="inspect",
            project_id="platform-workspace",
        ),
        user=user,
    )


def _node(user: dict, name: str, cpu: int) -> dict:
    return execution_nodes.create_node(
        execution_nodes.NodeCreate(
            name=name,
            capabilities=["java-pod", "maven", "gradle", "javac"],
            cpu_millis=cpu,
            memory_mb=16_384,
            disk_mb=100_000,
        ),
        user=user,
    )


def test_java_pod_uses_and_releases_a_resource_lease(runtime_db: Path, user: dict) -> None:
    pipeline = _pipeline(user)
    node = _node(user, "java-node-a", 8_000)

    pod = execution_nodes.create_java_pod(
        pipeline["id"],
        execution_nodes.JavaPodCreate(
            build_tool="maven",
            cpu_millis=2_000,
            memory_mb=4_096,
            disk_mb=8_192,
        ),
        user=user,
    )

    assert pod["state"] == "scheduled"
    assert pod["node"]["id"] == node["id"]
    assert pod["lease"]["state"] == "active"
    assert pod["lease"]["resources"]["cpu_millis"] == 2_000

    launch = execution_nodes.launch_spec(pod["id"], user=user)
    assert launch["image"].startswith("amosclaud-java-pod:")
    assert launch["security"]["run_as_non_root"] is True
    assert launch["mounts"][0]["target"] == "/workspace"

    execution_nodes.start_java_pod(
        pod["id"],
        execution_nodes.JavaPodStart(runtime_id="container-java-1"),
        user=user,
    )
    completed = execution_nodes.complete_java_pod(
        pod["id"],
        execution_nodes.JavaPodComplete(
            summary="Maven build and tests passed.",
            artifacts=[
                {
                    "kind": "jar",
                    "name": "service.jar",
                    "uri": "/artifacts/service.jar",
                }
            ],
            metrics={"duration_ms": 1200},
        ),
        user=user,
    )

    assert completed["state"] == "completed"
    assert completed["lease"]["state"] == "released"
    nodes = execution_nodes.list_nodes(user=user)["items"]
    assert nodes[0]["resources"]["used"]["cpu_millis"] == 0

    events = cooperation.cooperation_pipeline_events(pipeline["id"], after=0, limit=200, user=user)[
        "items"
    ]
    event_types = [event["event_type"] for event in events]
    assert "resource.lease.created" in event_types
    assert "java_pod.completed" in event_types
    assert "resource.lease.released" in event_types


def test_pipefail_reassigns_java_pod_when_node_goes_offline(runtime_db: Path, user: dict) -> None:
    pipeline = _pipeline(user)
    first = _node(user, "java-node-primary", 8_000)
    second = _node(user, "java-node-secondary", 4_000)

    pod = execution_nodes.create_java_pod(
        pipeline["id"],
        execution_nodes.JavaPodCreate(
            build_tool="gradle",
            cpu_millis=1_000,
            memory_mb=2_048,
            disk_mb=4_096,
            max_attempts=3,
        ),
        user=user,
    )
    assert pod["node"]["id"] == first["id"]

    execution_nodes.heartbeat_node(
        first["id"],
        execution_nodes.NodeHeartbeat(status="offline"),
        user=user,
    )

    with execution_nodes._db() as db:
        reassigned = execution_nodes._pod_json(
            db,
            execution_nodes._row(db, "cooperation_java_pods", pod["id"], user),
        )
    assert reassigned["state"] == "scheduled"
    assert reassigned["attempt"] == 2
    assert reassigned["node"]["id"] == second["id"]
    assert reassigned["lease"]["state"] == "active"

    failures = execution_nodes.pipefail_events(pipeline["id"], limit=100, user=user)["items"]
    assert failures[0]["kind"] == "node_unreachable"
    assert failures[0]["action"] == "retry_reassigned"


def test_java_node_requires_a_java_capability(runtime_db: Path, user: dict) -> None:
    with pytest.raises(Exception) as error:
        execution_nodes.create_node(
            execution_nodes.NodeCreate(
                name="python-only",
                capabilities=["python", "testing"],
            ),
            user=user,
        )
    assert "java" in str(error.value).lower()

from __future__ import annotations

from pathlib import Path

import pytest

from amoscloud_ai.api.routes import auth, execution_nodes, runtime_telemetry
from amoscloud_ai.api.routes import pipeline_cooperation as cooperation


@pytest.fixture
def telemetry_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    database = tmp_path / "telemetry.db"
    monkeypatch.setattr(auth, "DB_PATH", database)
    return database


@pytest.fixture
def user() -> dict:
    return {"id": 91, "email": "telemetry@example.com", "is_admin": False}


def _pipeline(user: dict, objective: str = "Verify telemetry layout") -> dict:
    return cooperation.create_cooperation_pipeline(
        cooperation.CooperationPipelineCreate(
            objective=objective,
            mode="inspect",
            project_id="telemetry-workspace",
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


def test_node_proposer_returns_ranked_telemetry_layout(
    telemetry_db: Path, user: dict
) -> None:
    pipeline = _pipeline(user)
    large = _node(user, "node-large", 16_000)
    small = _node(user, "node-small", 4_000)

    result = runtime_telemetry.propose_node(
        runtime_telemetry.NodeProposalRequest(
            pipeline_id=pipeline["id"],
            build_tool="maven",
            cpu_millis=2_000,
            memory_mb=4_096,
            disk_mb=8_192,
        ),
        user=user,
    )

    assert result["layout"] == "amosclaud.telemetry.node-proposer.v1"
    assert result["pipeline"]["id"] == pipeline["id"]
    assert result["eligible_nodes"] == 2
    assert result["selected_node_id"] == large["id"]
    assert result["proposals"][0]["selected"] is True
    assert result["proposals"][0]["rank"] == 1
    assert result["proposals"][1]["node_id"] == small["id"]
    assert result["proposals"][0]["resource_fit"]["cpu_millis"]["fits"] is True


def test_node_proposer_explains_ineligible_nodes(telemetry_db: Path, user: dict) -> None:
    node = _node(user, "offline-node", 2_000)
    execution_nodes.heartbeat_node(
        node["id"],
        execution_nodes.NodeHeartbeat(status="offline"),
        user=user,
    )

    result = runtime_telemetry.propose_node(
        runtime_telemetry.NodeProposalRequest(
            build_tool="gradle",
            cpu_millis=4_000,
            memory_mb=32_768,
            disk_mb=200_000,
        ),
        user=user,
    )

    proposal = result["proposals"][0]
    assert result["selected_node_id"] is None
    assert proposal["eligible"] is False
    assert "node status is offline" in proposal["reasons"]
    assert "insufficient cpu_millis" in proposal["reasons"]
    assert "insufficient memory_mb" in proposal["reasons"]


def test_all_pipefail_telemetry_contains_pipeline_graphics(
    telemetry_db: Path, user: dict
) -> None:
    pipeline = _pipeline(user, "Compile, recover, and report PipeFail")
    first = _node(user, "primary-node", 8_000)
    second = _node(user, "recovery-node", 4_000)
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

    execution_nodes.heartbeat_node(
        first["id"],
        execution_nodes.NodeHeartbeat(status="offline"),
        user=user,
    )
    reassigned = execution_nodes.fail_java_pod(
        pod["id"],
        execution_nodes.JavaPodFailure(
            error="Gradle compile failed after reassignment",
            kind="compile",
            retryable=False,
            metadata={"phase": "compile"},
        ),
        user=user,
    )
    assert reassigned["state"] == "failed"
    assert second["id"] != first["id"]

    telemetry = runtime_telemetry.all_pipefail_telemetry(
        pipeline_id=None,
        limit=500,
        user=user,
    )

    assert telemetry["layout"] == "amosclaud.telemetry.pipefail.v1"
    assert telemetry["scope"]["type"] == "all-pipelines"
    assert telemetry["summary"]["total"] == 2
    assert telemetry["summary"]["recovered"] == 1
    assert telemetry["summary"]["terminal"] == 1
    assert telemetry["summary"]["pipelines_affected"] == 1
    assert {item["kind"] for item in telemetry["items"]} == {
        "node_unreachable",
        "compile",
    }
    assert telemetry["items"][0]["metadata"] == {"phase": "compile"}

    graphic = telemetry["graphics"][0]
    assert graphic["layout"] == "amosclaud.graphics.pipefail-pipeline.v1"
    assert graphic["pipeline"]["id"] == pipeline["id"]
    assert graphic["summary"]["pipefail"] == 2
    assert graphic["summary"]["recovered"] == 1
    assert graphic["summary"]["terminal"] == 1
    assert {node["key"] for node in graphic["nodes"]} == {
        "pipeline",
        "java_pods",
        "pipefail",
        "recovered",
        "waiting",
        "terminal",
    }
    assert any(
        edge["from"] == "pipefail" and edge["to"] == "recovered"
        for edge in graphic["edges"]
    )


def test_pipeline_telemetry_returns_zero_failure_graphics(
    telemetry_db: Path, user: dict
) -> None:
    pipeline = _pipeline(user, "Pipeline without failures")

    telemetry = runtime_telemetry.pipeline_telemetry(
        pipeline["id"], limit=100, user=user
    )

    assert telemetry["scope"]["type"] == "pipeline"
    assert telemetry["summary"]["total"] == 0
    assert telemetry["graphics"][0]["pipeline"]["id"] == pipeline["id"]
    assert telemetry["graphics"][0]["summary"]["pipefail"] == 0

from __future__ import annotations

from postortores import DataRecord, EvidenceRecord, EventRecord, MemoryRecord, PostortoresEngine


def test_versioned_state_and_history(tmp_path):
    engine = PostortoresEngine(tmp_path / "postortores.db")
    first = engine.put(DataRecord("projects", "alpha", {"status": "planned"}))
    second = engine.put(DataRecord("projects", "alpha", {"status": "verified"}))

    assert first.version == 1
    assert second.version == 2
    assert engine.get("projects", "alpha").value["status"] == "verified"
    assert [item.version for item in engine.history("projects", "alpha")] == [1, 2]


def test_events_are_append_only_and_ordered(tmp_path):
    engine = PostortoresEngine(tmp_path / "postortores.db")
    one = engine.append_event(EventRecord("task:1", "planned", {"step": 1}, actor="agent"))
    two = engine.append_event(EventRecord("task:1", "executed", {"step": 2}, actor="runner"))

    events = engine.read_events("task:1")
    assert [event["id"] for event in events] == [one, two]
    assert [event["type"] for event in events] == ["planned", "executed"]
    assert all(event["hash"] for event in events)


def test_vector_memory_search(tmp_path):
    engine = PostortoresEngine(tmp_path / "postortores.db")
    engine.remember(MemoryRecord("agent:1", "python failure", embedding=[1.0, 0.0]))
    engine.remember(MemoryRecord("agent:1", "network failure", embedding=[0.0, 1.0]))

    results = engine.search_memory("agent:1", [0.9, 0.1])
    assert results[0]["content"] == "python failure"
    assert results[0]["score"] > results[1]["score"]


def test_verification_evidence_uses_truth_states(tmp_path):
    engine = PostortoresEngine(tmp_path / "postortores.db")
    evidence_id = engine.record_evidence(
        EvidenceRecord("build:42", "tests passed", "verified", {"exit_code": 0})
    )

    evidence = engine.evidence_for("build:42")
    assert evidence[0]["id"] == evidence_id
    assert evidence[0]["status"] == "verified"
    assert evidence[0]["proof"]["exit_code"] == 0


def test_graph_and_worker_leases(tmp_path):
    engine = PostortoresEngine(tmp_path / "postortores.db")
    engine.link("project:alpha", "owns", "repo:alpha", {"kind": "repository"})

    assert engine.neighbors("project:alpha", "owns")[0]["target"] == "repo:alpha"
    assert engine.acquire_lease("workspace:alpha", "worker-a", 60)
    assert not engine.acquire_lease("workspace:alpha", "worker-b", 60)


def test_health_identifies_native_contract(tmp_path):
    engine = PostortoresEngine(tmp_path / "postortores.db")
    health = engine.health()

    assert health["status"] == "ready"
    assert health["native_contract"] is True
    assert health["storage"] == "sqlite-bootstrap"

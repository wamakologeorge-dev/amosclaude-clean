from postortores import PostortoresEngine, PostortoresService


def test_service_scopes_state_between_principals(tmp_path):
    engine = PostortoresEngine(tmp_path / "postortores.db")
    alice = PostortoresService(engine, "alice")
    bob = PostortoresService(engine, "bob")

    alice.put_state("workspace", "project", {"name": "alpha"})
    bob.put_state("workspace", "project", {"name": "beta"})

    assert alice.get_state("workspace", "project").value == {"name": "alpha"}
    assert bob.get_state("workspace", "project").value == {"name": "beta"}
    assert len(alice.state_history("workspace", "project")) == 1
    assert len(bob.state_history("workspace", "project")) == 1
    engine.close()


def test_service_scopes_memory_and_graph(tmp_path):
    engine = PostortoresEngine(tmp_path / "postortores.db")
    first = PostortoresService(engine, "first")
    second = PostortoresService(engine, "second")

    first.remember("first memory", {"kind": "lesson"}, [1.0, 0.0])
    second.remember("second memory", {"kind": "lesson"}, [1.0, 0.0])

    assert [item["content"] for item in first.search_memory([1.0, 0.0])] == ["first memory"]
    assert [item["content"] for item in second.search_memory([1.0, 0.0])] == ["second memory"]

    first.link("repo:alpha", "owns", "workspace:alpha", {"source": "test"})
    assert first.neighbors("repo:alpha") == [
        {
            "target": "workspace:alpha",
            "relation": "owns",
            "metadata": {"source": "test"},
        }
    ]
    assert second.neighbors("repo:alpha") == []
    engine.close()


def test_service_evidence_events_and_leases(tmp_path):
    engine = PostortoresEngine(tmp_path / "postortores.db")
    service = PostortoresService(engine, "agent-1")

    event_id = service.append_event("task:7", "tests.completed", {"passed": 12})
    assert service.events("task:7")[0]["id"] == event_id

    evidence_id = service.record_evidence(
        "task:7",
        "tests completed",
        "verified",
        {"passed": 12, "failed": 0},
    )
    evidence = service.evidence("task:7")
    assert evidence[0]["id"] == evidence_id
    assert evidence[0]["status"] == "verified"

    assert service.acquire_lease("workspace:7", "worker-a", 60) is True
    assert service.acquire_lease("workspace:7", "worker-b", 60) is False
    assert service.acquire_lease("workspace:7", "worker-a", 60) is True
    engine.close()


def test_service_describe_reports_native_capabilities(tmp_path):
    engine = PostortoresEngine(tmp_path / "postortores.db")
    service = PostortoresService(engine, "physical-a1")

    description = service.describe()
    assert description["service"] == "Amosclaud Postortores"
    assert description["status"] == "ready"
    assert description["native_contract"] is True
    assert "semantic-agent-memory" in description["capabilities"]
    assert "verification-evidence" in description["capabilities"]
    assert "worker-leases" in description["capabilities"]
    engine.close()

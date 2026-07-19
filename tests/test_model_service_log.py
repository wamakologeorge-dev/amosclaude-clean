import json

from amosclaud_model.service_log import ModelServiceLog


def test_service_log_is_private_chained_and_summarized(tmp_path):
    log = ModelServiceLog(tmp_path)
    secret_prompt = "private customer source code"
    first = log.append(
        "inference.completed",
        request_id="request-1",
        prompt_fingerprint=log.fingerprint(secret_prompt),
        prompt_tokens=4,
        completion_tokens=6,
        total_tokens=10,
        latency_ms=12.5,
        outcome="success",
    )
    second = log.append(
        "inference.failed",
        request_id="request-2",
        prompt_fingerprint=log.fingerprint("another prompt"),
        outcome="error",
        error_type="RuntimeError",
    )
    raw = next((tmp_path / "logs" / "service").glob("*.jsonl")).read_text()
    assert secret_prompt not in raw
    assert second["previous_hash"] == first["event_hash"]
    assert log.verify()["valid"] is True
    assert log.summary() == {
        "events": 2,
        "completed": 1,
        "failed": 1,
        "total_tokens": 10,
        "average_latency_ms": 12.5,
        "last_sequence": 2,
    }


def test_service_log_detects_tampering_and_rejects_sensitive_fields(tmp_path):
    import pytest

    log = ModelServiceLog(tmp_path)
    log.append("inference.completed", request_id="request-1", outcome="success")
    path = next((tmp_path / "logs" / "service").glob("*.jsonl"))
    record = json.loads(path.read_text())
    record["outcome"] = "altered"
    path.write_text(json.dumps(record) + "\n")
    assert log.verify()["valid"] is False
    with pytest.raises(ValueError, match="Sensitive"):
        log.append("bad.event", prompt="must not be stored")

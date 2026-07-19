from pathlib import Path

import pytest

from Amosclaud.programming_bytes_system_cb import (
    CB_SEGMENTS,
    ProgrammingBytesRequestCB,
    ProgrammingBytesSystemCB,
    ProgrammingBytesSystemError,
)


def test_exact_literal_cb_path_exists_and_manifest_matches():
    result = ProgrammingBytesSystemCB().verify_layout(Path.cwd())
    assert result["valid"] is True
    assert result["segments"] == 28
    assert len(result["manifest_sha256"]) == 64


def test_programming_bytes_pipeline_executes_every_real_stage():
    system = ProgrammingBytesSystemCB()
    result = system.execute(
        ProgrammingBytesRequestCB(
            route="agent.build",
            payload=b"build and verify the Amosclaud server",
            method="POST",
            command="build",
            page="/control/server",
            host="localhost",
            repository="owner/project",
            metadata={
                "version": "1.0.0",
                "agent": "Builder Buddy",
                "checks": ["lint", "test"],
                "matrix_width": 3,
                "matrix_height": 2,
                "3d": True,
            },
        )
    )
    assert result.status == "completed"
    assert len(result.stages) == len(CB_SEGMENTS) == 28
    assert [stage.stage for stage in result.stages] == list(CB_SEGMENTS)
    assert result.output.json()["context"]["matrix"] == {"width": 3, "height": 2}
    assert result.output.json()["context"]["3d"] == {"enabled": True, "objects": 1}
    assert result.meter["input_bytes"] > 0
    assert result.output.sha256


@pytest.mark.parametrize(
    "changes,match",
    [
        ({"command": "rm"}, "allowlisted"),
        ({"page": "/safe/../../escape"}, "traversal"),
        ({"repository": "not-a-repository"}, "GitHub"),
        ({"method": "TRACE"}, "REST"),
    ],
)
def test_programming_bytes_pipeline_rejects_unsafe_inputs(changes, match):
    values = {
        "route": "agent.verify",
        "payload": b"safe",
        "command": "verify",
        "page": "/safe",
        "repository": "owner/project",
        "method": "POST",
    }
    values.update(changes)
    with pytest.raises(ProgrammingBytesSystemError, match=match):
        ProgrammingBytesSystemCB().execute(ProgrammingBytesRequestCB(**values))

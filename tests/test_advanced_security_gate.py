from __future__ import annotations

import io
import json
import urllib.error
from typing import Any

from scripts.ci.advanced_security_gate import evaluate_pull_request, render_markdown


class FakeResponse:
    def __init__(self, payload: object, status: int = 200) -> None:
        self.payload = payload
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def alert(number: int, severity: str = "low") -> dict[str, Any]:
    return {
        "number": number,
        "html_url": f"https://github.com/owner/repo/security/code-scanning/{number}",
        "rule": {
            "id": "py/example-threat",
            "security_severity_level": severity,
            "description": "Example security finding",
        },
        "most_recent_instance": {
            "location": {"path": "src/example.py", "start_line": 12}
        },
    }


def test_low_severity_alert_is_a_blocking_threat() -> None:
    calls: list[str] = []

    def urlopen(request, timeout=30):
        calls.append(request.full_url)
        return FakeResponse([alert(7, "low")])

    result = evaluate_pull_request(
        repository="owner/repo",
        pull_request=42,
        token="token",
        urlopen=urlopen,
    )

    assert result.status == "THREATS_DETECTED"
    assert result.exit_code == 1
    assert len(result.threats) == 1
    assert result.threats[0]["severity"] == "low"
    assert "pr=42" in calls[0]
    assert "state=open" in calls[0]
    assert "token" not in calls[0]
    assert "THREATS_DETECTED" in render_markdown(result)


def test_no_open_alerts_passes() -> None:
    result = evaluate_pull_request(
        repository="owner/repo",
        pull_request=42,
        token="token",
        urlopen=lambda request, timeout=30: FakeResponse([]),
    )

    assert result.status == "PASSED"
    assert result.exit_code == 0
    assert result.threats == ()


def test_api_unavailable_never_fails_open() -> None:
    def urlopen(request, timeout=30):
        raise urllib.error.HTTPError(
            request.full_url,
            403,
            "forbidden",
            {},
            io.BytesIO(b"{}"),
        )

    result = evaluate_pull_request(
        repository="owner/repo",
        pull_request=42,
        token="token",
        urlopen=urlopen,
    )

    assert result.status == "BLOCKED"
    assert result.exit_code == 2
    assert "unavailable" in result.detail


def test_paginates_all_alerts() -> None:
    calls: list[str] = []

    def urlopen(request, timeout=30):
        calls.append(request.full_url)
        if "&page=1" in request.full_url:
            return FakeResponse([alert(index) for index in range(100)])
        if "&page=2" in request.full_url:
            return FakeResponse([alert(101, "note")])
        raise AssertionError(request.full_url)

    result = evaluate_pull_request(
        repository="owner/repo",
        pull_request=42,
        token="token",
        urlopen=urlopen,
    )

    assert result.status == "THREATS_DETECTED"
    assert len(result.threats) == 101
    assert result.threats[-1]["severity"] == "note"
    assert any("&page=2" in call for call in calls)

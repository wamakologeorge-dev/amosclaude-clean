from __future__ import annotations

import json

from amosclaud_bot import ollama_connection


class _Response:
    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def test_connection_skips_cleanly_without_repository_secret(monkeypatch, capsys):
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)

    assert ollama_connection.verify_connection() == 0
    assert "Skipped" in capsys.readouterr().out


def test_connection_sends_bearer_key_without_printing_it(monkeypatch, tmp_path, capsys):
    secret = "ollama-secret-value"
    summary = tmp_path / "summary.md"
    captured: dict[str, object] = {}

    monkeypatch.setenv("OLLAMA_API_KEY", secret)
    monkeypatch.setenv("OLLAMA_URL", "https://ollama.com")
    monkeypatch.setenv("AMOSCLAUD_MODEL", "gpt-oss:120b")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["authorization"] = request.headers.get("Authorization")
        captured["timeout"] = timeout
        return _Response({"models": [{"name": "gpt-oss:120b"}]})

    monkeypatch.setattr(ollama_connection, "urlopen", fake_urlopen)

    assert ollama_connection.verify_connection() == 0
    output = capsys.readouterr().out
    assert captured == {
        "url": "https://ollama.com/api/tags",
        "authorization": f"Bearer {secret}",
        "timeout": 20,
    }
    assert "Authenticated successfully" in output
    assert secret not in output
    assert secret not in summary.read_text(encoding="utf-8")


def test_connection_rejects_invalid_endpoint(monkeypatch, capsys):
    monkeypatch.setenv("OLLAMA_API_KEY", "present")
    monkeypatch.setenv("OLLAMA_URL", "not-a-url")

    assert ollama_connection.verify_connection() == 1
    assert "invalid" in capsys.readouterr().err.lower()

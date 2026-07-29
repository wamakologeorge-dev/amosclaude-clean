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


def test_connection_requires_selected_model_when_requested(monkeypatch, capsys):
    monkeypatch.setenv("OLLAMA_API_KEY", "present")
    monkeypatch.setenv("AMOSCLAUD_MODEL", "wamakologeorge/amosclaud-clean:latest")
    monkeypatch.setenv("OLLAMA_REQUIRE_MODEL", "true")
    monkeypatch.setattr(
        ollama_connection,
        "urlopen",
        lambda _request, timeout: _Response({"models": [{"name": "gpt-oss:120b"}]}),
    )

    assert ollama_connection.verify_connection() == 1
    assert "not visible" in capsys.readouterr().err


def test_connection_probes_openai_compatible_completion(monkeypatch, capsys):
    secret = "ollama-secret-value"
    model = "wamakologeorge/amosclaud-clean:latest"
    requests: list[tuple[str, str | None, dict | None]] = []

    monkeypatch.setenv("OLLAMA_API_KEY", secret)
    monkeypatch.setenv("AMOSCLAUD_MODEL", model)
    monkeypatch.setenv("OLLAMA_REQUIRE_MODEL", "true")
    monkeypatch.setenv("OLLAMA_PROBE_COMPLETION", "true")

    def fake_urlopen(request, timeout):
        body = json.loads(request.data.decode("utf-8")) if request.data else None
        requests.append((request.full_url, request.headers.get("Authorization"), body))
        if request.full_url.endswith("/api/tags"):
            return _Response({"models": [{"name": model}]})
        assert timeout == 60
        return _Response(
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "AMOSCLAUD_OLLAMA_READY",
                        }
                    }
                ]
            }
        )

    monkeypatch.setattr(ollama_connection, "urlopen", fake_urlopen)

    assert ollama_connection.verify_connection() == 0
    assert requests[0][:2] == (
        "https://ollama.com/api/tags",
        f"Bearer {secret}",
    )
    assert requests[1][0] == "https://ollama.com/v1/chat/completions"
    assert requests[1][1] == f"Bearer {secret}"
    assert requests[1][2]["model"] == model
    output = capsys.readouterr().out
    assert "Completion probe passed" in output
    assert secret not in output


def test_connection_rejects_invalid_endpoint(monkeypatch, capsys):
    monkeypatch.setenv("OLLAMA_API_KEY", "present")
    monkeypatch.setenv("OLLAMA_URL", "not-a-url")

    assert ollama_connection.verify_connection() == 1
    assert "invalid" in capsys.readouterr().err.lower()

"""Tests for amosclaud_bot."""

from __future__ import annotations

import json

import pytest

from amosclaud_bot import AmosclaudBot, UnknownCommandError
from amosclaud_bot.errors import BotError
from amosclaud_bot.handlers import handle_help, handle_info, handle_ping


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def read(self):
        return json.dumps(self.payload).encode()


def _make_bot(monkeypatch, tmp_path, *, api_key="amos_aut_test"):
    # Stub urlopen so no real HTTP calls are made
    monkeypatch.setattr(
        "amosclaud_agent_sdk.client.urlopen",
        lambda _req, timeout: _FakeResponse({"pipeline_id": "p1", "status": "success", "reply": "done"}),
    )
    return AmosclaudBot(api_key=api_key, store_path=str(tmp_path / "sessions"))


# ---------------------------------------------------------------------------
# Built-in handlers
# ---------------------------------------------------------------------------


def test_ping_returns_pong(monkeypatch, tmp_path):
    bot = _make_bot(monkeypatch, tmp_path)
    assert bot.dispatch("!ping") == "pong"


def test_help_lists_registered_commands(monkeypatch, tmp_path):
    bot = _make_bot(monkeypatch, tmp_path)
    reply = bot.dispatch("!help")
    assert "!ping" in reply
    assert "!help" in reply
    assert "!info" in reply


def test_info_includes_session_id(monkeypatch, tmp_path):
    bot = _make_bot(monkeypatch, tmp_path)
    reply = bot.dispatch("!info")
    assert "session:" in reply


# ---------------------------------------------------------------------------
# Command registration
# ---------------------------------------------------------------------------


def test_register_custom_command(monkeypatch, tmp_path):
    bot = _make_bot(monkeypatch, tmp_path)
    bot.register("greet", lambda _msg, _bot: "hello")
    assert bot.dispatch("!greet") == "hello"


def test_register_duplicate_raises(monkeypatch, tmp_path):
    bot = _make_bot(monkeypatch, tmp_path)
    bot.register("custom", lambda _msg, _bot: "x")
    with pytest.raises(ValueError, match="already registered"):
        bot.register("custom", lambda _msg, _bot: "y")


def test_unknown_command_raises(monkeypatch, tmp_path):
    bot = _make_bot(monkeypatch, tmp_path)
    with pytest.raises(UnknownCommandError):
        bot.dispatch("!nonexistent")


def test_blank_command_name_raises(monkeypatch, tmp_path):
    bot = _make_bot(monkeypatch, tmp_path)
    with pytest.raises(ValueError):
        bot.register("", lambda _msg, _bot: "x")


# ---------------------------------------------------------------------------
# Agent fallback
# ---------------------------------------------------------------------------


def test_natural_language_routes_to_agent(monkeypatch, tmp_path):
    bot = _make_bot(monkeypatch, tmp_path)
    reply = bot.dispatch("List open pull requests")
    assert reply == "done"


def test_empty_message_raises(monkeypatch, tmp_path):
    bot = _make_bot(monkeypatch, tmp_path)
    with pytest.raises(BotError):
        bot.dispatch("   ")


# ---------------------------------------------------------------------------
# Handler unit tests (no bot needed)
# ---------------------------------------------------------------------------


def test_handle_ping_standalone():
    assert handle_ping("", None) == "pong"  # type: ignore[arg-type]


def test_handle_help_empty_bot_has_no_handlers():
    class _Stub:
        def info(self):
            return {"registered_commands": [], "session_id": "x", "system_prompt": None}

    assert "No commands" in handle_help("", _Stub())  # type: ignore[arg-type]


def test_handle_info_shows_session():
    class _Stub:
        def info(self):
            return {"session_id": "abc-123", "registered_commands": ["ping"], "system_prompt": None}

    reply = handle_info("", _Stub())  # type: ignore[arg-type]
    assert "abc-123" in reply
    assert "ping" in reply

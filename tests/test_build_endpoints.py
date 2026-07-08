"""Tests for the Amoscloud AI build endpoints."""

import io
import json
import sys
import types
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Stub the anthropic package so tests run without installing it
# ---------------------------------------------------------------------------

def _make_anthropic_stub():
    module = types.ModuleType("anthropic")

    class _Message:
        def __init__(self, text):
            self.content = [MagicMock(text=text)]

    class _Messages:
        def create(self, **kwargs):
            return _Message("## Project Plan\n- Step 1\n## Implementation Outline\n- file.py")

    class Anthropic:
        def __init__(self, **kwargs):
            self.messages = _Messages()

    module.Anthropic = Anthropic
    return module


sys.modules.setdefault("anthropic", _make_anthropic_stub())

# Now import the app (anthropic is already stubbed)
from src.amoscloud_ai.main import app  # noqa: E402

client = TestClient(app)


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

def test_index_returns_html():
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "Amoscloud AI" in resp.text


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "healthy"


# ---------------------------------------------------------------------------
# /build/instructions
# ---------------------------------------------------------------------------

def test_build_instructions_success():
    resp = client.post(
        "/build/instructions",
        data={"instructions": "Build a REST API with FastAPI", "context": ""},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "completed"
    assert body["mode"] == "instructions"
    assert body["generated_plan"] is not None


def test_build_instructions_empty_returns_failed():
    resp = client.post("/build/instructions", data={"instructions": "   ", "context": ""})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "failed"


# ---------------------------------------------------------------------------
# /build/photo
# ---------------------------------------------------------------------------

def _png_bytes() -> bytes:
    """Return minimal valid 1×1 PNG bytes."""
    return (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde"
        b"\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )


def test_build_photo_success():
    resp = client.post(
        "/build/photo",
        files={"photo": ("screenshot.png", io.BytesIO(_png_bytes()), "image/png")},
        data={"instructions": ""},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "completed"
    assert body["mode"] == "photo"
    assert body["generated_plan"] is not None


def test_build_photo_non_image_rejected():
    resp = client.post(
        "/build/photo",
        files={"photo": ("data.csv", io.BytesIO(b"a,b,c"), "text/csv")},
        data={"instructions": ""},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "failed"
    assert "image" in body["error"].lower()


def test_build_photo_too_large_rejected():
    large = b"X" * (21 * 1024 * 1024)  # 21 MB > 20 MB limit
    resp = client.post(
        "/build/photo",
        files={"photo": ("big.png", io.BytesIO(large), "image/png")},
        data={"instructions": ""},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "failed"
    assert "large" in body["error"].lower()

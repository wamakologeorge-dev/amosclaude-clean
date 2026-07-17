#!/usr/bin/env python3
"""Verify that Amosclaud can reach a real model station and complete inference."""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE_URL = os.getenv("AMOSCLAUD_MODEL_URL", "http://127.0.0.1:8090").rstrip("/")
TOKEN = os.getenv("AMOSCLAUD_MODEL_TOKEN", "")
TIMEOUT = float(os.getenv("AMOSCLAUD_MODEL_HEALTH_TIMEOUT", "330"))


def request_json(path: str, payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Accept": "application/json"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    request = urllib.request.Request(f"{BASE_URL}{path}", data=data, headers=headers)
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        content_type = response.headers.get_content_type()
        body = response.read().decode("utf-8", errors="replace")
        if content_type != "application/json":
            raise RuntimeError(f"Expected JSON from {path}, received {content_type}: {body[:160]}")
        return json.loads(body)


def main() -> int:
    started = time.monotonic()
    try:
        health = request_json("/health")
        if health.get("ready") is not True:
            print(json.dumps({"ready": False, "stage": "health", "response": health}, indent=2))
            return 2

        inference = request_json(
            "/v1/chat/completions",
            {
                "model": health.get("model") or os.getenv("AMOSCLAUD_MODEL_NAME", "qwen2.5-coder:7b"),
                "messages": [{"role": "user", "content": "Reply with exactly: AMOSCLAUD_MODEL_READY"}],
                "temperature": 0,
                "max_tokens": 32,
            },
        )
        choices = inference.get("choices") or []
        content = ((choices[0].get("message") or {}).get("content") if choices else "") or ""
        if "AMOSCLAUD_MODEL_READY" not in content:
            raise RuntimeError(f"Inference returned an unexpected response: {content[:200]}")

        print(
            json.dumps(
                {
                    "ready": True,
                    "endpoint": BASE_URL,
                    "model": health.get("model"),
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                    "inference": "verified",
                },
                indent=2,
            )
        )
        return 0
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        print(json.dumps({"ready": False, "stage": "http", "status": exc.code, "detail": detail}, indent=2))
    except urllib.error.URLError as exc:
        print(json.dumps({"ready": False, "stage": "connection", "error": str(exc.reason)}, indent=2))
    except Exception as exc:  # bounded diagnostic output
        print(json.dumps({"ready": False, "stage": "validation", "error": str(exc)}, indent=2))
    return 1


if __name__ == "__main__":
    sys.exit(main())

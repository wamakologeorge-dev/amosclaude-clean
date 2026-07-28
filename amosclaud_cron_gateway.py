#!/usr/bin/env python3
"""Run the daily proposal agent through the canonical Amosclaud provider route.

The original cron client assumed every deployment exposed ``/v1/chat/completions``.
Amosclaud.com exposes its authenticated provider route under
``/api/v1/provider/chat/completions``. This adapter prefers the configured path,
falls back only on 404/405 route mismatches, validates JSON responses, and then
hands the completion back to the existing bounded patch/verification pipeline.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

import amosclaud_cron_agent as agent


def _base_url() -> str:
    return (
        os.getenv("AMOSCLAUD_PROVIDER_API_URL", "").strip()
        or os.getenv("AMOSCLAUD_API_URL", "").strip()
        or "https://www.amosclaud.com"
    ).rstrip("/")


def _completion_paths() -> list[str]:
    configured = os.getenv("AMOSCLAUD_API_COMPLETIONS_PATH", "").strip()
    candidates = [
        configured,
        "/api/v1/provider/chat/completions",
        "/v1/chat/completions",
    ]
    paths: list[str] = []
    for raw in candidates:
        if not raw:
            continue
        path = f"/{raw.lstrip('/')}"
        if path not in paths:
            paths.append(path)
    return paths


def _payload(prompt: str) -> dict[str, Any]:
    return {
        "model": agent.MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are Amosclaud's scheduled repository engineer. "
                    "Return exactly one unified git diff inside a diff code fence. "
                    "Make one small, useful, backward-compatible change to an "
                    "existing runtime component and update or add tests. Do not "
                    "modify workflows, agent policy, secrets, environment files, "
                    "infrastructure, dependency files, or instructions. Do not "
                    "create an unused top-level module."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "stream": False,
    }


def _extract_content(result: Any) -> str:
    try:
        content = result["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise agent.CronAgentError(
            "Amosclaud gateway returned an invalid completion payload"
        ) from exc
    if not isinstance(content, str) or not content.strip():
        raise agent.CronAgentError("Amosclaud gateway returned no proposal")
    return content


def call_amosclaud(prompt: str) -> str:
    if not agent.API_KEY:
        raise agent.CronAgentError("AMOSCLAUD_API_KEY is not configured")

    body = json.dumps(_payload(prompt)).encode("utf-8")
    route_errors: list[str] = []
    for path in _completion_paths():
        request = urllib.request.Request(
            f"{_base_url()}{path}",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {agent.API_KEY}",
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "Amosclaud-Cron-Agent/2.0",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                raw = response.read().decode("utf-8", errors="replace")
                content_type = str(response.headers.get("Content-Type", "")).lower()
                if "json" not in content_type:
                    raise agent.CronAgentError(
                        "Amosclaud gateway returned a non-JSON response from "
                        f"{path}: {agent.redact(raw[:500])}"
                    )
                try:
                    return _extract_content(json.loads(raw))
                except json.JSONDecodeError as exc:
                    raise agent.CronAgentError(
                        f"Amosclaud gateway returned invalid JSON from {path}"
                    ) from exc
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            if error.code in {404, 405}:
                route_errors.append(f"{path} -> HTTP {error.code}: {agent.redact(detail[:300])}")
                continue
            raise agent.CronAgentError(
                f"Amosclaud gateway returned HTTP {error.code} at {path}: "
                f"{agent.redact(detail)}"
            ) from error
        except urllib.error.URLError as error:
            raise agent.CronAgentError(
                f"Amosclaud gateway is unreachable: {error.reason}"
            ) from error

    detail = "; ".join(route_errors) or "no completion routes were configured"
    raise agent.CronAgentError(
        "Amosclaud gateway has no compatible POST completion route: " + detail
    )


def main() -> int:
    agent.call_amosclaud = call_amosclaud
    return agent.run_daily_cycle()


if __name__ == "__main__":
    raise SystemExit(main())

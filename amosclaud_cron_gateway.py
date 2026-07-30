#!/usr/bin/env python3
"""Run the daily proposal agent through the canonical Amosclaud provider route.

The public provider route is preferred. If that route is unavailable or its
installation key was revoked, the same repository-owned provider policy may use
the configured Ollama/self-hosted route. The fallback remains bounded and never
prints credentials.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

import amosclaud_cron_agent as agent
from sitecustomize import normalize_public_amosclaud_url


def _base_url() -> str:
    configured = (
        os.getenv("AMOSCLAUD_PROVIDER_API_URL", "").strip()
        or os.getenv("AMOSCLAUD_API_URL", "").strip()
        or "https://www.amosclaud.com"
    )
    return normalize_public_amosclaud_url(configured)


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


def _system_prompt() -> str:
    return (
        "You are Amosclaud's scheduled repository engineer. Return exactly one "
        "unified git diff inside a diff code fence. Make one small, useful, "
        "backward-compatible change to an existing runtime component and update "
        "or add tests. Do not modify workflows, agent policy, secrets, environment "
        "files, infrastructure, dependency files, or instructions. Do not create "
        "an unused top-level module."
    )


def _payload(prompt: str) -> dict[str, Any]:
    return {
        "model": agent.MODEL,
        "messages": [
            {"role": "system", "content": _system_prompt()},
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


def _provider_fallback(prompt: str) -> str:
    """Use the shared first-party provider policy, including Ollama when configured."""
    from amoscloud_ai import provider

    result = provider.reply(
        [{"role": "user", "content": prompt}],
        _system_prompt(),
    )
    if not result.ok or not result.reply.strip():
        detail = result.error or "no usable fallback model route"
        raise agent.CronAgentError(
            "Amosclaud provider fallback is unavailable: " + agent.redact(detail)
        )
    return result.reply


def call_amosclaud(prompt: str) -> str:
    body = json.dumps(_payload(prompt)).encode("utf-8")
    route_errors: list[str] = []

    if agent.API_KEY:
        for path in _completion_paths():
            request = urllib.request.Request(
                f"{_base_url()}{path}",
                data=body,
                method="POST",
                headers={
                    "Authorization": f"Bearer {agent.API_KEY}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "User-Agent": "Amosclaud-Cron-Agent/3.0",
                },
            )
            try:
                with urllib.request.urlopen(request, timeout=180) as response:
                    raw = response.read().decode("utf-8", errors="replace")
                    content_type = str(response.headers.get("Content-Type", "")).lower()
                    if "json" not in content_type:
                        route_errors.append(
                            f"{path} -> non-JSON response: {agent.redact(raw[:300])}"
                        )
                        break
                    try:
                        return _extract_content(json.loads(raw))
                    except json.JSONDecodeError:
                        route_errors.append(f"{path} -> invalid JSON")
                        break
            except urllib.error.HTTPError as error:
                detail = error.read().decode("utf-8", errors="replace")
                route_errors.append(
                    f"{path} -> HTTP {error.code}: {agent.redact(detail[:300])}"
                )
                if error.code in {404, 405}:
                    continue
                break
            except urllib.error.URLError as error:
                route_errors.append(f"{path} -> unreachable: {error.reason}")
                break
    else:
        route_errors.append("AMOSCLAUD_API_KEY is not configured")

    try:
        return _provider_fallback(prompt)
    except Exception as fallback_error:
        detail = "; ".join(route_errors) or "no public route was attempted"
        raise agent.CronAgentError(
            "Amosclaud gateway and provider fallback are unavailable: "
            f"{detail}; fallback={agent.redact(str(fallback_error))}"
        ) from fallback_error


def main() -> int:
    agent.call_amosclaud = call_amosclaud
    return agent.run_daily_cycle()


if __name__ == "__main__":
    raise SystemExit(main())

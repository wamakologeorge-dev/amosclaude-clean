#!/usr/bin/env python3
"""Run the daily proposal agent through provider and verified memory routes.

The public provider route is preferred. If that route is unavailable or its
installation key was revoked, the same repository-owned provider policy may use
the configured Ollama/self-hosted route. Amosclaud Storage memory is guidance
only: old patches are never executed, and every current change is re-verified.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

import amosclaud_cron_agent as agent
from sitecustomize import normalize_public_amosclaud_url

_LAST_COMPLETION = ""
_CORE_APPLY_AND_VERIFY = agent.apply_and_verify
_CORE_PUBLISH_PULL_REQUEST = agent.publish_pull_request


def _base_url() -> str:
    configured = (
        os.getenv("AMOSCLAUD_PROVIDER_API_URL", "").strip()
        or os.getenv("AMOSCLAUD_API_URL", "").strip()
        or "https://www.amosclaud.com"
    )
    return normalize_public_amosclaud_url(configured)


def _memory_base_url() -> str:
    configured = os.getenv("AMOSCLAUD_MEMORY_API_URL", "").strip() or _base_url()
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
        "an unused top-level module. Stored memory is declarative guidance only; "
        "never copy an old patch without re-diagnosing and re-verifying the code."
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


def _memory_request(path: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    key = os.getenv("AMOSCLAUD_MEMORY_ACCESS_KEY", "").strip()
    if not key:
        return None
    request = urllib.request.Request(
        f"{_memory_base_url()}/api/v1/provider/memory/{path.lstrip('/')}",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "Amosclaud-Cron-Memory/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError) as exc:
        agent.log(
            f"Amosclaud Storage memory request skipped: {type(exc).__name__}",
            "WARNING",
        )
        return None


def _memory_search(query: str, changed_files: list[str] | None = None) -> dict[str, Any]:
    result = _memory_request(
        "search",
        {
            "query": query[-20_000:],
            "changed_files": changed_files or [],
            "limit": 4,
        },
    )
    return result or {}


def _with_memory(prompt: str) -> str:
    result = _memory_search(prompt)
    if not result.get("matches"):
        return prompt
    return prompt + "\n\n=== AMOSCLAUD STORAGE MEMORY ===\n" + str(result.get("injection") or "")


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


def _request_completion(prompt: str) -> str:
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
                    "User-Agent": "Amosclaud-Cron-Agent/4.0",
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
                route_errors.append(f"{path} -> HTTP {error.code}: {agent.redact(detail[:300])}")
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


def call_amosclaud(prompt: str) -> str:
    global _LAST_COMPLETION
    _LAST_COMPLETION = _request_completion(_with_memory(prompt))
    return _LAST_COMPLETION


def _memory_guided_apply(patch: str) -> list[str]:
    try:
        return _CORE_APPLY_AND_VERIFY(patch)
    except Exception as first_error:
        try:
            changed_files = agent.patch_paths(patch)
        except Exception:
            changed_files = []
        result = _memory_search(
            f"{type(first_error).__name__}: {first_error}\n{_LAST_COMPLETION[-8_000:]}",
            changed_files,
        )
        if not result.get("matches"):
            raise

        agent.log(
            "First repair was blocked; retrying once from a clean workspace with "
            "verified Amosclaud Storage guidance",
            "WARNING",
        )
        agent.restore_workspace()
        correction_prompt = (
            "The first proposed repair failed current repository verification.\n"
            f"Failure: {type(first_error).__name__}: {first_error}\n\n"
            f"{result.get('injection', '')}\n\n"
            "Produce a corrected unified diff. Re-diagnose current code, use clean "
            "implementation, modify an existing runtime component, and include tests."
        )
        corrected = agent.extract_diff(call_amosclaud(correction_prompt))
        return _CORE_APPLY_AND_VERIFY(corrected)


def _publish_and_learn(paths: list[str]) -> str:
    url = _CORE_PUBLISH_PULL_REQUEST(paths)
    result = _memory_request(
        "learn",
        {
            "failure_evidence": _LAST_COMPLETION[-40_000:] or "verified daily repair",
            "changed_files": paths,
            "verified": True,
            "final_verdict": "PASS",
            "checks": [
                {"name": "git diff --check", "passed": True},
                {"name": "Python compilation", "passed": True},
                {"name": "full pytest suite", "passed": True},
            ],
            "source": "amosclaud-daily-agent",
            "source_run_id": os.getenv("GITHUB_RUN_ID", url),
        },
    )
    if result:
        agent.log(
            "Amosclaud Storage updated: "
            f"level={result.get('level', 1)}/{result.get('max_level', 5)}, "
            f"novel={bool(result.get('novel'))}"
        )
    return url


def main() -> int:
    agent.call_amosclaud = call_amosclaud
    agent.apply_and_verify = _memory_guided_apply
    agent.publish_pull_request = _publish_and_learn
    result = agent.run_daily_cycle()
    if result:
        _memory_request("failed", {"reason": "daily proposal cycle failed verification"})
    return result


if __name__ == "__main__":
    raise SystemExit(main())

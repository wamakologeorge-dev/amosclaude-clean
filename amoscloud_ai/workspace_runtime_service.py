"""Truthful service check for the isolated Amosclaud workspace runtime."""

from __future__ import annotations

import httpx

from amoscloud_ai import workspace_runtime


def _transport_failure(detail: str) -> dict:
    return {
        "id": "workspace-runtime",
        "name": "Isolated cloud workspace runtime",
        "state": "unreachable",
        "explanation": (
            "The execution plane is configured, but the control plane could not "
            "establish a network connection to its health endpoint."
        ),
        "evidence": (
            "authenticated GET /health on AMOSCLAUD_WORKSPACE_RUNTIME_URL; "
            "no Docker socket is mounted in the public web service"
        ),
        "remediation": detail,
    }


def check() -> dict:
    evidence = (
        "authenticated GET /health on AMOSCLAUD_WORKSPACE_RUNTIME_URL; "
        "no Docker socket is mounted in the public web service"
    )
    try:
        health = workspace_runtime.runtime_health()
    except httpx.ConnectError:
        return _transport_failure(
            "Start or restart the workspace-runtime service and verify that "
            "AMOSCLAUD_WORKSPACE_RUNTIME_URL points to its reachable private "
            "HTTP(S) host and port. When the control plane runs on another host, "
            "set AMOSCLAUD_WORKSPACE_RUNTIME_BIND to a protected private interface "
            "and redeploy the runtime."
        )
    except httpx.TimeoutException:
        return _transport_failure(
            "The workspace-runtime health probe timed out. Verify the configured "
            "host, port, reverse proxy, firewall rules, and Docker daemon health, "
            "then restart the runtime service."
        )
    except httpx.RequestError:
        return _transport_failure(
            "The workspace-runtime HTTP request failed before a response was "
            "received. Verify AMOSCLAUD_WORKSPACE_RUNTIME_URL, DNS, TLS, routing, "
            "and the runtime service process."
        )
    if not health.get("configured"):
        return {
            "id": "workspace-runtime",
            "name": "Isolated cloud workspace runtime",
            "state": "not_configured",
            "explanation": (
                "The execution plane is not configured, so browser terminals and "
                "container workspaces cannot start. Repository editing remains available."
            ),
            "evidence": evidence,
            "remediation": (
                "Deploy services/workspace_runtime on a separate Docker host, then set "
                "AMOSCLAUD_WORKSPACE_RUNTIME_URL, AMOSCLAUD_WORKSPACE_PUBLIC_URL, and "
                "AMOSCLAUD_WORKSPACE_RUNTIME_TOKEN on the control plane."
            ),
        }
    if health.get("ok") and health.get("docker_ready"):
        return {
            "id": "workspace-runtime",
            "name": "Isolated cloud workspace runtime",
            "state": "operational",
            "explanation": (
                "The dedicated execution plane authenticated successfully and its "
                "container runtime answered the health probe."
            ),
            "evidence": evidence,
        }
    return {
        "id": "workspace-runtime",
        "name": "Isolated cloud workspace runtime",
        "state": "unreachable",
        "explanation": (
            "The execution plane is configured but did not prove that its Docker "
            "runtime and service credential are ready."
        ),
        "evidence": evidence,
        "remediation": str(
            health.get("detail")
            or "Check the private runtime endpoint, shared repository volume, and service token."
        ),
    }

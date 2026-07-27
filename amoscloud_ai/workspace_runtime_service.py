"""Truthful service check for the isolated Amosclaud workspace runtime."""

from __future__ import annotations

from amoscloud_ai import workspace_runtime


def check() -> dict:
    health = workspace_runtime.runtime_health()
    evidence = (
        "authenticated GET /health on AMOSCLAUD_WORKSPACE_RUNTIME_URL; "
        "no Docker socket is mounted in the public web service"
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

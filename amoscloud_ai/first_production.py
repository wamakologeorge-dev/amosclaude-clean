"""Amosclaud-first production truth and provider-boundary contracts."""

from __future__ import annotations

from typing import Any

AUTHORITATIVE_PROVIDER = "amosclaud"
CANONICAL_DOMAIN = "https://amosclauds.com"
EXTERNAL_PROVIDERS = ("github", "railway", "vercel", "circleci")


def ci_color(status: str | None) -> str:
    """Return the product color for one authoritative Amosclaud CI state."""

    normalized = str(status or "").strip().lower()
    if normalized in {"success", "passed", "green"}:
        return "green"
    if normalized in {"failed", "failure", "error", "red"}:
        return "red"
    if normalized in {"pending", "running", "queued", "in_progress"}:
        return "amber"
    return "gray"


def merge_allowed(*, ci_status: str | None, head_sha: str, verified_sha: str | None) -> bool:
    """Only Amosclaud CI success for the exact PR head unlocks an Amosclaud merge."""

    return (
        ci_color(ci_status) == "green"
        and bool(head_sha)
        and bool(verified_sha)
        and head_sha == verified_sha
    )


def production_truth(
    *,
    ci_status: str | None,
    head_sha: str = "",
    verified_sha: str | None = None,
    external: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build a truthful status card where external providers are advisory only."""

    color = ci_color(ci_status)
    return {
        "authority": AUTHORITATIVE_PROVIDER,
        "canonical_domain": CANONICAL_DOMAIN,
        "ci": {
            "status": str(ci_status or "unknown").lower(),
            "color": color,
            "authoritative": True,
            "verified_sha": verified_sha,
        },
        "merge_allowed": merge_allowed(
            ci_status=ci_status,
            head_sha=head_sha,
            verified_sha=verified_sha,
        ),
        "external_providers": {
            name: {
                "status": str((external or {}).get(name, "unknown")),
                "authoritative": False,
                "blocks_amosclaud_merge": False,
            }
            for name in EXTERNAL_PROVIDERS
        },
    }


def capability_matrix() -> dict[str, bool]:
    """Machine-readable true/false product readiness contract."""

    return {
        "amosclaud_is_production_authority": True,
        "native_issues": True,
        "native_pull_requests": True,
        "native_merge": True,
        "amosclaud_ci_green_red_truth": True,
        "external_ci_required_for_amosclaud_merge": False,
        "railway_required_for_production_truth": False,
        "github_required_for_native_repository_workflow": False,
        "vercel_required_for_production_truth": False,
        "third_party_adapters_supported": True,
        "domain_name_runs_compute_by_itself": False,
        "vercel_serverless_local_sqlite_is_durable": False,
        "dns_change_is_performed_by_application_code": False,
    }


def manifest() -> dict[str, Any]:
    """Public product contract for Amosclaud-first production."""

    return {
        "schema": "amosclaud.first-production/v1",
        "product": "Amosclaud",
        "authority": AUTHORITATIVE_PROVIDER,
        "canonical_domain": CANONICAL_DOMAIN,
        "production_gate": "amosclaud_ci",
        "merge_rule": "exact_head_sha_must_have_green_amosclaud_ci",
        "external_provider_role": "optional_adapter_and_evidence",
        "capabilities": capability_matrix(),
    }


__all__ = [
    "AUTHORITATIVE_PROVIDER",
    "CANONICAL_DOMAIN",
    "EXTERNAL_PROVIDERS",
    "capability_matrix",
    "ci_color",
    "manifest",
    "merge_allowed",
    "production_truth",
]

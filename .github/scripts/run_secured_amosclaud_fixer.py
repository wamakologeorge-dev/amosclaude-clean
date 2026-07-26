#!/usr/bin/env python3
"""Verify a one-time Fixer grant, scrub authority secrets, then run Fixer."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.amosclaud_security import (  # noqa: E402
    Capability,
    CommandState,
    Principal,
    SecurityError,
)
from src.amosclaud_security.repair import fixer_objective  # noqa: E402
from src.amosclaud_security.runtime import (  # noqa: E402
    authority_for_workspace,
    repository_identity,
    target_revision,
)

FAILURE_LOG = ROOT / os.getenv("AMOSCLAUD_FAILURE_LOG", "amosclaud-failure.log")
REPORT_PATH = ROOT / "amosclaud-fixer-report.json"
FIXER_PATH = ROOT / ".github" / "scripts" / "amosclaud_fixer.py"


def _safe_child_environment() -> dict[str, str]:
    environment = dict(os.environ)
    for name in (
        "AMOSCLAUD_COMMAND_BUS_SECRET",
        "AMOSCLAUD_FIXER_GRANT",
        "AMOSCLAUD_PUBLISHER_GRANT",
        "AMOSCLAUD_AUTONOMOUS_TOKEN",
        "GH_TOKEN",
        "GITHUB_TOKEN",
        "ACTIONS_RUNTIME_TOKEN",
        "ACTIONS_ID_TOKEN_REQUEST_TOKEN",
    ):
        environment.pop(name, None)
    environment["AMOSCLAUD_SECURITY_ENFORCE"] = "true"
    environment["AMOSCLAUD_FIXER_SECURITY_WRAPPED"] = "true"
    return environment


def _write_security_report(
    *,
    report: dict,
    command_id: str,
    parent_command_id: str | None,
    correlation_id: str,
    repository: str,
    target_sha: str,
    authority,
    status: str,
) -> None:
    events = authority.audit_events(command_id=command_id)
    security = {
        "enforced": True,
        "grant_verified": True,
        "grant_consumed": True,
        "grant_material_exposed": False,
        "authority_secret_exposed_to_model": False,
        "github_credentials_exposed_to_model": False,
        "fixer_command_id": command_id,
        "root_command_id": parent_command_id,
        "correlation_id": correlation_id,
        "repository": repository,
        "target_sha": target_sha,
        "state": status,
        "audit_event_count": len(events),
        "audit_head": events[-1]["event_hash"] if events else None,
        "audit_chain_valid": authority.verify_audit_chain(),
    }
    report["security"] = security
    REPORT_PATH.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")


def main() -> int:
    grant_token = os.getenv("AMOSCLAUD_FIXER_GRANT", "").strip()
    if not grant_token:
        raise SystemExit("AMOSCLAUD_FIXER_GRANT is required")
    if not FIXER_PATH.is_file():
        raise SystemExit("Amosclaud Fixer script is missing")

    raw_failure = (
        FAILURE_LOG.read_text(encoding="utf-8", errors="replace")
        if FAILURE_LOG.is_file()
        else ""
    )
    objective = fixer_objective(raw_failure)
    repository = repository_identity(ROOT, os.getenv("GITHUB_REPOSITORY", ""))
    target_sha = os.getenv("TARGET_SHA", "").strip() or target_revision(ROOT)
    authority = authority_for_workspace(ROOT, required=True)
    assert authority is not None

    try:
        decision = authority.verify(
            grant_token,
            expected_subject=Principal.FIXER,
            repository=repository,
            target_sha=target_sha,
            objective=objective,
            required_capabilities=[Capability.REPAIR_APPLY],
            consume=True,
        )
    except SecurityError as exc:
        raise SystemExit(f"Fixer security grant rejected: {type(exc).__name__}") from exc

    grant = decision.grant
    assert grant is not None
    for state, actor in (
        (CommandState.RECEIVED, Principal.FIXER),
        (CommandState.AUTHORIZED, Principal.FIXER),
        (CommandState.PLANNED, Principal.AUTONOMOUS),
        (CommandState.FIXER_AUTHORIZED, Principal.FIXER),
    ):
        authority.transition(
            command_id=grant.command_id,
            correlation_id=grant.correlation_id,
            state=state,
            actor=actor,
            detail={"workflow_run": os.getenv("GITHUB_RUN_ID", "")},
        )

    process = subprocess.run(
        [sys.executable, str(FIXER_PATH)],
        cwd=ROOT,
        env=_safe_child_environment(),
        text=True,
        check=False,
    )

    report: dict = {}
    if REPORT_PATH.is_file():
        try:
            loaded = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                report = loaded
        except json.JSONDecodeError:
            report = {}

    verified = process.returncode == 0 and report.get("status") == "verified"
    if verified:
        for state, actor in (
            (CommandState.PATCH_PROPOSED, Principal.FIXER),
            (CommandState.VERIFYING, Principal.VERIFIER),
            (CommandState.VERIFIED, Principal.VERIFIER),
        ):
            authority.transition(
                command_id=grant.command_id,
                correlation_id=grant.correlation_id,
                state=state,
                actor=actor,
                detail={
                    "changed_files": len(report.get("changed_files") or []),
                    "fixer_exit_code": process.returncode,
                },
            )
        status = CommandState.VERIFIED.value
    else:
        authority.transition(
            command_id=grant.command_id,
            correlation_id=grant.correlation_id,
            state=CommandState.FAILED,
            actor=Principal.FIXER,
            detail={
                "fixer_exit_code": process.returncode,
                "report_status": report.get("status"),
            },
        )
        status = CommandState.FAILED.value

    report.setdefault("status", "failed")
    _write_security_report(
        report=report,
        command_id=grant.command_id,
        parent_command_id=grant.parent_command_id,
        correlation_id=grant.correlation_id,
        repository=repository,
        target_sha=target_sha,
        authority=authority,
        status=status,
    )
    print(f"AMOSCLAUD_SECURE_FIXER_STATUS={status}")
    return 0 if verified else (process.returncode or 1)


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Consume and record the Verifier -> Publisher capability grant."""

from __future__ import annotations

import argparse
import json
import os
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
from src.amosclaud_security.repair import (  # noqa: E402
    load_report,
    publish_objective,
    verification_receipt,
)
from src.amosclaud_security.runtime import authority_for_workspace  # noqa: E402

AUTHORIZATION_PATH = ROOT / ".git" / "amosclaud-publish-authorization.json"


def _authorize(report_path: str) -> int:
    token = os.getenv("AMOSCLAUD_PUBLISHER_GRANT", "").strip()
    if not token:
        raise SystemExit("AMOSCLAUD_PUBLISHER_GRANT is required")
    report = load_report(report_path)
    if report.get("status") != "verified":
        raise SystemExit("repair report is not verified")
    security = report.get("security") or {}
    if not isinstance(security, dict) or security.get("audit_chain_valid") is not True:
        raise SystemExit("repair report has no valid security audit chain")

    fixer_command_id = str(security.get("fixer_command_id") or "")
    correlation_id = str(security.get("correlation_id") or "")
    repository = str(security.get("repository") or "")
    target_sha = str(security.get("target_sha") or "")
    if not all((fixer_command_id, correlation_id, repository, target_sha)):
        raise SystemExit("repair report has incomplete security identity")

    changed_files = sorted(
        str(item) for item in (report.get("changed_files") or []) if isinstance(item, str)
    )
    if not changed_files or len(changed_files) > 25:
        raise SystemExit("repair report has an invalid changed-file set")
    if any(path.startswith(".github/") for path in changed_files):
        raise SystemExit("bounded autonomous repair cannot publish .github paths")

    receipt = verification_receipt(report)
    objective = publish_objective(report)
    authority = authority_for_workspace(ROOT, required=True)
    assert authority is not None
    try:
        decision = authority.verify(
            token,
            expected_subject=Principal.PUBLISHER,
            repository=repository,
            target_sha=target_sha,
            objective=objective,
            required_capabilities=[
                Capability.BRANCH_CREATE,
                Capability.PULL_REQUEST_CREATE,
                Capability.AUTO_MERGE_REQUEST,
            ],
            consume=True,
            expected_parent_command_id=fixer_command_id,
        )
    except SecurityError as exc:
        raise SystemExit(
            f"Publisher security grant rejected: {type(exc).__name__}"
        ) from exc

    grant = decision.grant
    assert grant is not None
    grant_files = sorted(
        str(item) for item in (grant.constraints.get("allowed_files") or [])
    )
    if grant_files != changed_files:
        raise SystemExit("publisher grant changed-file set does not match verified report")
    if grant.constraints.get("verification_receipt") != receipt:
        raise SystemExit("publisher grant verification receipt does not match report")
    if grant.constraints.get("allow_default_branch_write") is not False:
        raise SystemExit("publisher grant does not prohibit default-branch writes")
    if grant.constraints.get("require_required_checks") is not True:
        raise SystemExit("publisher grant does not require repository checks")

    authority.transition(
        command_id=fixer_command_id,
        correlation_id=correlation_id,
        state=CommandState.PUBLISH_AUTHORIZED,
        actor=Principal.PUBLISHER,
        detail={
            "publisher_command_id": grant.command_id,
            "verification_receipt": receipt,
            "changed_files": changed_files,
        },
    )
    authorization = {
        "authorized": True,
        "publisher_command_id": grant.command_id,
        "fixer_command_id": fixer_command_id,
        "correlation_id": correlation_id,
        "repository": repository,
        "target_sha": target_sha,
        "verification_receipt": receipt,
        "allowed_files": changed_files,
        "allow_default_branch_write": False,
        "require_required_checks": True,
        "grant_material_stored": False,
    }
    AUTHORIZATION_PATH.write_text(
        json.dumps(authorization, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    AUTHORIZATION_PATH.chmod(0o600)
    print("AMOSCLAUD_PUBLISH_AUTHORIZED=true")
    return 0


def _finalize(report_path: str, outcome: str, reference: str) -> int:
    report = load_report(report_path)
    security = report.get("security") or {}
    authorization = json.loads(AUTHORIZATION_PATH.read_text(encoding="utf-8"))
    if not isinstance(authorization, dict) or authorization.get("authorized") is not True:
        raise SystemExit("publisher authorization record is invalid")
    if authorization.get("fixer_command_id") != security.get("fixer_command_id"):
        raise SystemExit("publisher authorization does not match repair command")
    if authorization.get("verification_receipt") != verification_receipt(report):
        raise SystemExit("publisher authorization receipt changed")

    authority = authority_for_workspace(ROOT, required=True)
    assert authority is not None
    command_id = str(authorization["fixer_command_id"])
    correlation_id = str(authorization["correlation_id"])
    if outcome == "success":
        authority.transition(
            command_id=command_id,
            correlation_id=correlation_id,
            state=CommandState.PUBLISHED,
            actor=Principal.PUBLISHER,
            detail={"reference": reference},
        )
        authority.transition(
            command_id=command_id,
            correlation_id=correlation_id,
            state=CommandState.MERGE_PENDING,
            actor=Principal.GITHUB,
            detail={
                "reference": reference,
                "required_checks": True,
                "auto_merge_requested": True,
            },
        )
    else:
        authority.transition(
            command_id=command_id,
            correlation_id=correlation_id,
            state=CommandState.FAILED,
            actor=Principal.PUBLISHER,
            detail={"reference": reference, "outcome": outcome},
        )
    print(f"AMOSCLAUD_PUBLISH_FINAL_STATE={outcome}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="action", required=True)
    authorize = subparsers.add_parser("authorize")
    authorize.add_argument("--report", required=True)
    finalize = subparsers.add_parser("finalize")
    finalize.add_argument("--report", required=True)
    finalize.add_argument("--outcome", choices=("success", "failed"), required=True)
    finalize.add_argument("--reference", default="")
    args = parser.parse_args()
    if args.action == "authorize":
        return _authorize(args.report)
    return _finalize(args.report, args.outcome, args.reference)


if __name__ == "__main__":
    raise SystemExit(main())

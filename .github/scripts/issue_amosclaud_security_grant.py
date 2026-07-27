#!/usr/bin/env python3
"""Issue one-time Amosclaud CI grants without exposing the authority secret."""

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
    bounded_repair_constraints,
)
from src.amosclaud_security.repair import (  # noqa: E402
    fixer_objective,
    load_report,
    publish_objective,
    verification_receipt,
)
from src.amosclaud_security.runtime import (  # noqa: E402
    authority_for_workspace,
    repository_identity,
    target_revision,
)

PROTECTED_PREFIXES = (
    ".git/",
    ".amosclaud/",
    ".github/",
    "Infrastructure/",
    "infrastructure/",
)
PROTECTED_PATHS = (
    "AGENTS.md",
    "docs/PYTHON_AUTONOMOUS_ENGINEERING_BOOK.md",
    "SECURITY.md",
    "CODEOWNERS",
    "Dockerfile",
    "railway.json",
    "vercel.json",
)


def _output(name: str, value: str, *, secret: bool = False) -> None:
    if secret:
        print(f"::add-mask::{value}")
    output = os.getenv("GITHUB_OUTPUT", "").strip()
    if output:
        with Path(output).open("a", encoding="utf-8") as handle:
            handle.write(f"{name}={value}\n")
    print(f"AMOSCLAUD_SECURITY_{name.upper()}={value if not secret else '[MASKED]'}")


def _repair(args: argparse.Namespace) -> int:
    evidence = Path(args.failure_log).read_text(encoding="utf-8", errors="replace")
    objective = fixer_objective(evidence)
    repository = repository_identity(ROOT, args.repository)
    target_sha = args.target_sha or target_revision(ROOT)
    authority = authority_for_workspace(ROOT, required=True)
    assert authority is not None
    constraints = bounded_repair_constraints(
        max_changed_files=25,
        protected_prefixes=PROTECTED_PREFIXES,
        protected_paths=PROTECTED_PATHS,
        approval_profile="verified-ci-failure",
    )
    root_grant = authority.issue(
        issuer=Principal.BOT,
        subject=Principal.AUTONOMOUS,
        repository=repository,
        target_sha=target_sha,
        objective=objective,
        capabilities=[Capability.REPAIR_PLAN],
        constraints=constraints,
        source={
            "kind": "github-workflow-run",
            "id": args.source_id,
            "failure_log": str(Path(args.failure_log).name),
        },
        approval={
            "kind": "verified-ci-failure",
            "decision": "approved",
            "workflow_run": args.source_id,
        },
        ttl_seconds=900,
    )
    root_decision = authority.verify(
        root_grant,
        expected_subject=Principal.AUTONOMOUS,
        repository=repository,
        target_sha=target_sha,
        objective=objective,
        required_capabilities=[Capability.REPAIR_PLAN],
        consume=True,
    )
    root = root_decision.grant
    assert root is not None
    for state, actor in (
        (CommandState.RECEIVED, Principal.BOT),
        (CommandState.AUTHORIZED, Principal.AUTONOMOUS),
        (CommandState.PLANNED, Principal.AUTONOMOUS),
    ):
        authority.transition(
            command_id=root.command_id,
            correlation_id=root.correlation_id,
            state=state,
            actor=actor,
            detail={"workflow_run": args.source_id},
        )
    fixer_grant = authority.issue(
        issuer=Principal.AUTONOMOUS,
        subject=Principal.FIXER,
        repository=repository,
        target_sha=target_sha,
        objective=objective,
        capabilities=[Capability.REPAIR_APPLY],
        constraints=constraints,
        source={
            "kind": "autonomous-ci-plan",
            "id": root.command_id,
            "workflow_run": args.source_id,
        },
        approval=root.approval,
        ttl_seconds=900,
        correlation_id=root.correlation_id,
        parent_command_id=root.command_id,
    )
    _output("fixer_grant", fixer_grant, secret=True)
    _output("root_command_id", root.command_id)
    _output("correlation_id", root.correlation_id)
    _output("security_objective", objective)
    _output("repository", repository)
    _output("target_sha", target_sha)
    return 0


def _publish(args: argparse.Namespace) -> int:
    report = load_report(args.report)
    if report.get("status") != "verified":
        raise SystemExit("repair report is not verified")
    changed_files = [
        str(item) for item in (report.get("changed_files") or []) if isinstance(item, str)
    ]
    if not changed_files or len(changed_files) > 25:
        raise SystemExit("verified report has an invalid changed-file set")
    security = report.get("security") or {}
    if not isinstance(security, dict):
        raise SystemExit("verified report is missing security evidence")
    fixer_command_id = str(security.get("fixer_command_id") or "")
    correlation_id = str(security.get("correlation_id") or "")
    repository = str(security.get("repository") or "")
    target_sha = str(security.get("target_sha") or "")
    if not all((fixer_command_id, correlation_id, repository, target_sha)):
        raise SystemExit("verified report has incomplete security evidence")
    receipt = verification_receipt(report)
    objective = publish_objective(report)
    authority = authority_for_workspace(ROOT, required=True)
    assert authority is not None
    publisher_grant = authority.issue(
        issuer=Principal.VERIFIER,
        subject=Principal.PUBLISHER,
        repository=repository,
        target_sha=target_sha,
        objective=objective,
        capabilities=[
            Capability.BRANCH_CREATE,
            Capability.PULL_REQUEST_CREATE,
            Capability.AUTO_MERGE_REQUEST,
        ],
        constraints={
            "verification_receipt": receipt,
            "allowed_files": sorted(changed_files),
            "max_changed_files": 25,
            "allow_default_branch_write": False,
            "require_required_checks": True,
        },
        source={
            "kind": "verified-repair-report",
            "id": receipt,
            "workflow_run": args.source_id,
        },
        approval={"kind": "verified-ci-failure", "decision": "approved"},
        ttl_seconds=600,
        correlation_id=correlation_id,
        parent_command_id=fixer_command_id,
    )
    _output("publisher_grant", publisher_grant, secret=True)
    _output("publish_objective", objective)
    _output("verification_receipt", receipt)
    _output("allowed_files_json", json.dumps(sorted(changed_files), separators=(",", ":")))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="mode", required=True)

    repair = subparsers.add_parser("repair")
    repair.add_argument("--failure-log", required=True)
    repair.add_argument("--repository", default=os.getenv("GITHUB_REPOSITORY", ""))
    repair.add_argument("--target-sha", default=os.getenv("TARGET_SHA", ""))
    repair.add_argument("--source-id", default=os.getenv("GITHUB_RUN_ID", "local"))

    publish = subparsers.add_parser("publish")
    publish.add_argument("--report", required=True)
    publish.add_argument("--source-id", default=os.getenv("GITHUB_RUN_ID", "local"))

    args = parser.parse_args()
    return _repair(args) if args.mode == "repair" else _publish(args)


if __name__ == "__main__":
    raise SystemExit(main())

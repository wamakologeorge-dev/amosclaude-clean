#!/usr/bin/env python3
"""Create bounded, deterministic Amosclaud repairs from real CI failure logs.

This program intentionally does not commit, push, or open pull requests. It runs in
an unprivileged GitHub Actions job, edits only existing files named by the failed
workflow logs, and writes a machine-readable report. A separate verification job
must approve the resulting patch before a write-enabled publishing job can use it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Iterable

from amoscloud_ai.repair_engine import Doctor, Finding, Fixer, Severity

ALLOWED_REPAIR_CODES = frozenset(
    {
        "json-syntax",
        "missing-final-newline",
        "trailing-whitespace",
        "unpinned-action",
        "yaml-tabs",
    }
)

PROTECTED_TOOLING_PATHS = frozenset(
    {
        ".github/workflows/amosclaud-autofix.yml",
        "scripts/amosclaud_autofix.py",
        "tests/test_amosclaud_autofix.py",
    }
)

PATH_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_.-])"
    r"((?:(?:[A-Za-z]:)?/|\.?\.?/)?(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+\."
    r"(?:py|json|ya?ml|sh|html|css|js|mjs|cjs|toml|md))"
    r"(?=[:\s\"')\],]|$)",
    re.IGNORECASE,
)


def _candidate_suffixes(root: Path, candidate: str) -> list[str]:
    cleaned = candidate.strip().replace("\\", "/").removeprefix("./")
    normalized = cleaned.lstrip("/")
    trials = [normalized]
    parts = [part for part in normalized.split("/") if part]
    repository_indexes = [index for index, part in enumerate(parts) if part == root.name]
    if repository_indexes:
        suffix = "/".join(parts[repository_indexes[-1] + 1 :])
        if suffix:
            trials.insert(0, suffix)
    return list(dict.fromkeys(item for item in trials if item))


def _relative_existing_path(root: Path, candidate: str) -> str | None:
    root = root.resolve()
    for cleaned in _candidate_suffixes(root, candidate):
        if cleaned in PROTECTED_TOOLING_PATHS:
            continue
        path = (root / cleaned).resolve()
        try:
            relative = path.relative_to(root)
        except ValueError:
            continue
        if path.is_file():
            return relative.as_posix()
    return None


def extract_candidate_paths(log_text: str, root: Path, limit: int = 25) -> list[str]:
    """Return existing repository files explicitly mentioned by CI logs."""

    discovered: list[str] = []
    for match in PATH_PATTERN.finditer(log_text):
        relative = _relative_existing_path(root, match.group(1))
        if relative and relative not in discovered:
            discovered.append(relative)
        if len(discovered) >= limit:
            break
    return discovered


def findings_for_path(doctor: Doctor, root: Path, relative: str) -> list[Finding]:
    path = root / relative
    findings = list(doctor._basic_text_checks(path))
    suffix = path.suffix.lower()
    if suffix == ".py":
        findings.extend(doctor._python_syntax(path))
    elif suffix == ".json":
        findings.extend(doctor._json_syntax(path))
    elif suffix == ".sh":
        findings.extend(doctor._shell_syntax(path))
    elif suffix in {".yml", ".yaml"}:
        findings.extend(doctor._workflow_checks(path))
    elif suffix == ".html":
        findings.extend(doctor._local_assets(path))
    return findings


def _serialize_findings(findings: Iterable[Finding]) -> list[dict[str, object]]:
    return [asdict(item) for item in findings]


def run_repair(root: Path, log_text: str) -> dict[str, object]:
    """Apply and recheck only low-risk repairs for files proven by CI logs."""

    root = root.resolve()
    doctor = Doctor(root)
    fixer = Fixer(root)
    candidates = extract_candidate_paths(log_text, root)
    log_digest = hashlib.sha256(log_text.encode("utf-8", errors="replace")).hexdigest()

    report: dict[str, object] = {
        "schema": "amosclaud.github-autofix.v1",
        "status": "no-candidates",
        "log_sha256": log_digest,
        "candidate_paths": candidates,
        "allowed_repair_codes": sorted(ALLOWED_REPAIR_CODES),
        "findings_before": [],
        "findings_after": [],
        "repairs": [],
        "changed_files": [],
    }
    if not candidates:
        return report

    before: list[Finding] = []
    for relative in candidates:
        before.extend(findings_for_path(doctor, root, relative))
    report["findings_before"] = _serialize_findings(before)

    repairable = [
        item
        for item in before
        if item.severity == Severity.REPAIRABLE
        and item.code in ALLOWED_REPAIR_CODES
        and item.path in candidates
    ]
    if not repairable:
        report["status"] = "no-safe-repair"
        return report

    selected_paths = sorted({item.path for item in repairable if item.path})
    snapshots = {relative: (root / relative).read_bytes() for relative in selected_paths}
    repairs = fixer.apply(repairable)
    changed_files = sorted({item.path for item in repairs if item.changed})
    report["repairs"] = [asdict(item) for item in repairs]

    after: list[Finding] = []
    for relative in candidates:
        after.extend(findings_for_path(doctor, root, relative))
    report["findings_after"] = _serialize_findings(after)

    blockers = [
        item for item in after if item.path in changed_files and item.severity != Severity.INFO
    ]
    if not changed_files or blockers:
        for relative, content in snapshots.items():
            (root / relative).write_bytes(content)
        report["status"] = "rolled-back"
        report["changed_files"] = []
        return report

    report["status"] = "repaired"
    report["changed_files"] = changed_files
    return report


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="Checked-out failed commit")
    parser.add_argument("--logs", type=Path, required=True, help="Failed GitHub Actions logs")
    parser.add_argument("--report", type=Path, required=True, help="JSON report destination")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    log_text = args.logs.read_text(encoding="utf-8", errors="replace") if args.logs.exists() else ""
    report = run_repair(args.root, log_text)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

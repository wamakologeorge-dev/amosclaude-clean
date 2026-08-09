#!/usr/bin/env python3
"""Create bounded Amosclaud repairs from real GitHub security and quality evidence.

This program intentionally does not commit, push, or open pull requests. It runs in
an unprivileged GitHub Actions job, edits only existing files named by trusted
workflow evidence, and writes a machine-readable report. A separate verification
job must approve the exact patch before a write-enabled publishing job can use it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
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

QUALITY_TOOL_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "black": (
        re.compile(r"\bblack(?:\s+--check|\s+--diff|\s+would)", re.IGNORECASE),
        re.compile(r"\bwould reformat\b", re.IGNORECASE),
    ),
    "isort": (
        re.compile(r"\bisort\b", re.IGNORECASE),
        re.compile(r"imports? (?:are|is) incorrectly sorted", re.IGNORECASE),
    ),
    "ruff": (
        re.compile(r"\bruff\s+(?:check|format)\b", re.IGNORECASE),
        re.compile(r"\bwould reformat\b.*\bruff\b", re.IGNORECASE),
    ),
}

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


def detect_quality_tools(log_text: str) -> list[str]:
    """Identify deterministic quality tools explicitly named by failure evidence."""

    return [
        tool
        for tool, patterns in QUALITY_TOOL_PATTERNS.items()
        if any(pattern.search(log_text) for pattern in patterns)
    ]


def _quality_command(tool: str, paths: list[str]) -> list[str]:
    if tool == "black":
        return [sys.executable, "-m", "black", "--quiet", "--", *paths]
    if tool == "isort":
        return [sys.executable, "-m", "isort", "--quiet", "--", *paths]
    if tool == "ruff":
        return [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--fix-only",
            "--exit-zero",
            "--",
            *paths,
        ]
    raise ValueError(f"unsupported quality tool: {tool}")


def apply_quality_repairs(
    root: Path,
    candidates: list[str],
    log_text: str,
) -> tuple[list[str], list[dict[str, object]]]:
    """Run only the formatter/linter proven by the failed quality log."""

    tools = detect_quality_tools(log_text)
    python_paths = [path for path in candidates if Path(path).suffix.lower() == ".py"]
    results: list[dict[str, object]] = []
    if not python_paths:
        return tools, results

    for tool in tools:
        command = _quality_command(tool, python_paths)
        try:
            completed = subprocess.run(
                command,
                cwd=root,
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
            results.append(
                {
                    "tool": tool,
                    "command": command,
                    "return_code": completed.returncode,
                    "passed": completed.returncode == 0,
                    "output": ((completed.stdout or "") + (completed.stderr or ""))[-8000:],
                }
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            results.append(
                {
                    "tool": tool,
                    "command": command,
                    "return_code": None,
                    "passed": False,
                    "output": str(exc),
                }
            )
    return tools, results


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
    """Apply and recheck low-risk repairs for files proven by GitHub evidence."""

    root = root.resolve()
    doctor = Doctor(root)
    fixer = Fixer(root)
    candidates = extract_candidate_paths(log_text, root)
    log_digest = hashlib.sha256(log_text.encode("utf-8", errors="replace")).hexdigest()

    report: dict[str, object] = {
        "schema": "amosclaud.github-autofix.v2",
        "status": "no-candidates",
        "log_sha256": log_digest,
        "candidate_paths": candidates,
        "allowed_repair_codes": sorted(ALLOWED_REPAIR_CODES),
        "quality_tools": [],
        "quality_results": [],
        "findings_before": [],
        "findings_after": [],
        "repairs": [],
        "changed_files": [],
    }
    if not candidates:
        return report

    snapshots = {relative: (root / relative).read_bytes() for relative in candidates}
    before: list[Finding] = []
    for relative in candidates:
        before.extend(findings_for_path(doctor, root, relative))
    report["findings_before"] = _serialize_findings(before)

    quality_tools, quality_results = apply_quality_repairs(root, candidates, log_text)
    report["quality_tools"] = quality_tools
    report["quality_results"] = quality_results

    repairable = [
        item
        for item in before
        if item.severity == Severity.REPAIRABLE
        and item.code in ALLOWED_REPAIR_CODES
        and item.path in candidates
    ]
    repairs = fixer.apply(repairable) if repairable else []
    report["repairs"] = [asdict(item) for item in repairs]

    changed_files = sorted(
        relative
        for relative, original in snapshots.items()
        if (root / relative).read_bytes() != original
    )

    after: list[Finding] = []
    for relative in candidates:
        after.extend(findings_for_path(doctor, root, relative))
    report["findings_after"] = _serialize_findings(after)

    failed_quality = [item for item in quality_results if not item.get("passed")]
    blockers = [
        item for item in after if item.path in changed_files and item.severity != Severity.INFO
    ]
    if not changed_files:
        report["status"] = "no-safe-repair"
        return report

    if failed_quality or blockers:
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

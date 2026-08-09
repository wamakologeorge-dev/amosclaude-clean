#!/usr/bin/env python3
"""Compare exact base and head Bandit reports without ignoring any severity.

Every finding introduced by the pull-request head is blocking. Findings already
present in the exact base revision remain visible as repository security debt,
but do not make an unrelated pull request permanently unmergeable.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_LINE = re.compile(r"^\s*(\d+)\s+(.*)$")


@dataclass(frozen=True)
class Finding:
    test_id: str
    test_name: str
    severity: str
    confidence: str
    filename: str
    line_number: int
    issue_text: str
    source_line: str
    more_info: str

    @property
    def fingerprint(self) -> tuple[str, str, str, str]:
        return (
            self.test_id,
            self.filename,
            self.issue_text,
            self.source_line,
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "test_id": self.test_id,
            "test_name": self.test_name,
            "severity": self.severity,
            "confidence": self.confidence,
            "filename": self.filename,
            "line_number": self.line_number,
            "issue_text": self.issue_text,
            "source_line": self.source_line,
            "more_info": self.more_info,
        }


@dataclass(frozen=True)
class GateResult:
    status: str
    base_count: int
    head_count: int
    new_findings: tuple[Finding, ...]
    resolved_count: int
    detail: str

    @property
    def exit_code(self) -> int:
        if self.status == "PASSED":
            return 0
        if self.status == "THREATS_DETECTED":
            return 1
        return 2

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": "amosclaud.bandit-pr-threat-gate.v1",
            "status": self.status,
            "base_finding_count": self.base_count,
            "head_finding_count": self.head_count,
            "new_threat_count": len(self.new_findings),
            "resolved_finding_count": self.resolved_count,
            "new_threats": [finding.as_dict() for finding in self.new_findings],
            "detail": self.detail,
            "exit_code": self.exit_code,
        }


def _source_line(code: object, line_number: int) -> str:
    text = str(code or "")
    fallback: list[str] = []
    for raw_line in text.splitlines():
        match = _LINE.match(raw_line)
        if not match:
            normalized = " ".join(raw_line.split())
            if normalized:
                fallback.append(normalized)
            continue
        candidate_number = int(match.group(1))
        normalized = " ".join(match.group(2).split())
        if candidate_number == line_number:
            return normalized
        if normalized:
            fallback.append(normalized)
    return " | ".join(fallback)


def _finding(value: Mapping[str, object]) -> Finding:
    line_number = int(value.get("line_number") or 0)
    filename = str(value.get("filename") or "").replace("\\", "/").lstrip("./")
    return Finding(
        test_id=str(value.get("test_id") or "UNKNOWN"),
        test_name=str(value.get("test_name") or "unknown"),
        severity=str(value.get("issue_severity") or "UNKNOWN").upper(),
        confidence=str(value.get("issue_confidence") or "UNKNOWN").upper(),
        filename=filename,
        line_number=line_number,
        issue_text=str(value.get("issue_text") or "Security finding"),
        source_line=_source_line(value.get("code"), line_number),
        more_info=str(value.get("more_info") or ""),
    )


def load_report(path: Path) -> tuple[Finding, ...]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not read Bandit report: {path}") from exc
    results = payload.get("results") if isinstance(payload, Mapping) else None
    if not isinstance(results, list):
        raise ValueError(f"Bandit report has no results list: {path}")
    findings = [_finding(item) for item in results if isinstance(item, Mapping)]
    return tuple(findings)


def compare_reports(base: Sequence[Finding], head: Sequence[Finding]) -> GateResult:
    base_counter = Counter(finding.fingerprint for finding in base)
    head_counter = Counter(finding.fingerprint for finding in head)
    remaining = base_counter.copy()
    new_findings: list[Finding] = []
    for finding in head:
        fingerprint = finding.fingerprint
        if remaining[fingerprint] > 0:
            remaining[fingerprint] -= 1
        else:
            new_findings.append(finding)

    resolved_count = sum((base_counter - head_counter).values())
    ordered = tuple(
        sorted(
            new_findings,
            key=lambda finding: (
                {"HIGH": 0, "MEDIUM": 1, "LOW": 2}.get(finding.severity, 3),
                finding.filename,
                finding.line_number,
                finding.test_id,
            ),
        )
    )
    if ordered:
        return GateResult(
            "THREATS_DETECTED",
            len(base),
            len(head),
            ordered,
            resolved_count,
            "every AST finding introduced by the exact head revision is blocking",
        )
    return GateResult(
        "PASSED",
        len(base),
        len(head),
        (),
        resolved_count,
        "the exact head revision introduced no new AST security findings",
    )


def render_markdown(result: GateResult) -> str:
    marker = "🟩" if result.status == "PASSED" else "🟥"
    lines = [
        "### Amosclaud Differential AST Threat Gate",
        "",
        f"**Result:** {marker} {result.status}",
        f"**Base findings:** {result.base_count}",
        f"**Head findings:** {result.head_count}",
        f"**New blocking threats:** {len(result.new_findings)}",
        f"**Resolved findings:** {result.resolved_count}",
        f"**Detail:** {result.detail}",
        "",
        "Existing base findings remain visible security debt; no severity is ignored.",
    ]
    for finding in result.new_findings[:30]:
        location = f"{finding.filename}:{finding.line_number}"
        lines.append(
            f"- `{finding.severity}` `{finding.test_id}` at `{location}` — " f"{finding.issue_text}"
        )
    if len(result.new_findings) > 30:
        lines.append(f"- ...and {len(result.new_findings) - 30} more new threat(s)")
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--head", type=Path, required=True)
    parser.add_argument("--json", dest="json_path", type=Path)
    parser.add_argument("--markdown", dest="markdown_path", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = compare_reports(load_report(args.base), load_report(args.head))
    except ValueError as exc:
        result = GateResult("BLOCKED", 0, 0, (), 0, str(exc))

    payload = json.dumps(result.as_dict(), indent=2, sort_keys=True)
    report = render_markdown(result)
    print(payload)
    print(report)
    if args.json_path:
        args.json_path.write_text(payload + "\n", encoding="utf-8")
    if args.markdown_path:
        args.markdown_path.write_text(report, encoding="utf-8")
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())

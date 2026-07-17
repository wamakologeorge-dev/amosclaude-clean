#!/usr/bin/env python3
"""Audit production code for placeholder and status-only behavior.

The scanner is intentionally conservative: it ignores documentation, tests, generated
assets, HTML input placeholder attributes, and explicitly allowlisted lines. Findings
are emitted as machine-readable JSON and the process exits non-zero when production
code contains language that commonly hides a missing operation.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

PRODUCTION_ROOTS = (
    "amoscloud_ai",
    "apps",
    "src",
    "web",
)

IGNORED_PARTS = {
    ".git",
    ".venv",
    "__pycache__",
    "dist",
    "build",
    "node_modules",
    "tests",
    "test",
    "docs",
}

TEXT_SUFFIXES = {
    ".py",
    ".js",
    ".mjs",
    ".cjs",
    ".ts",
    ".tsx",
    ".jsx",
    ".html",
    ".css",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
}

ALLOW_MARKER = "real-operation-audit: allow"

SUSPICIOUS_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("not-implemented", re.compile(r"\bnot\s+implemented\b", re.IGNORECASE)),
    ("coming-soon", re.compile(r"\bcoming\s+soon\b", re.IGNORECASE)),
    ("placeholder-data", re.compile(r"\bplaceholder\s+(?:data|result|response|content)\b", re.IGNORECASE)),
    ("mock-data", re.compile(r"\bmock(?:ed)?\s+(?:data|result|response|repository|service)\b", re.IGNORECASE)),
    ("fake-data", re.compile(r"\bfake\s+(?:data|result|response|repository|service)\b", re.IGNORECASE)),
    ("simulated-operation", re.compile(r"\bsimulat(?:e|ed|ing)\s+(?:operation|deployment|test|build|commit|merge)\b", re.IGNORECASE)),
    ("status-only", re.compile(r"\bstatus[- ]only\b", re.IGNORECASE)),
    ("todo-operation", re.compile(r"\bTODO\b.*\b(?:implement|wire|connect|execute|run|save|commit|merge|deploy)\b", re.IGNORECASE)),
)

HTML_INPUT_PLACEHOLDER = re.compile(r"\bplaceholder\s*=\s*(['\"]).*?\1", re.IGNORECASE)


@dataclass(frozen=True)
class Finding:
    rule: str
    path: str
    line: int
    text: str


def _production_files(root: Path) -> Iterable[Path]:
    for relative_root in PRODUCTION_ROOTS:
        base = root / relative_root
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            if any(part in IGNORED_PARTS for part in path.relative_to(root).parts):
                continue
            yield path


def scan(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for path in _production_files(root):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for line_number, raw_line in enumerate(lines, start=1):
            if ALLOW_MARKER in raw_line:
                continue
            candidate = HTML_INPUT_PLACEHOLDER.sub("", raw_line) if path.suffix.lower() == ".html" else raw_line
            for rule, pattern in SUSPICIOUS_PATTERNS:
                if pattern.search(candidate):
                    findings.append(
                        Finding(
                            rule=rule,
                            path=path.relative_to(root).as_posix(),
                            line=line_number,
                            text=raw_line.strip()[:240],
                        )
                    )
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, help="Write the JSON report to this path")
    args = parser.parse_args()

    root = args.root.resolve()
    findings = scan(root)
    report = {
        "root": str(root),
        "production_roots": list(PRODUCTION_ROOTS),
        "finding_count": len(findings),
        "findings": [asdict(item) for item in findings],
    }
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())

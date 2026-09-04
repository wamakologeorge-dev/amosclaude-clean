#!/usr/bin/env python3
"""Amosclaud Crash Shield: warn on code patterns that can crash or hang production.

The scanner is intentionally dependency-free so it can run before application
installation. Findings are advisory by default; --fail-on-critical makes only
critical findings block CI.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "dist", "build", "vendor", "__pycache__"}
TEXT_SUFFIXES = {".py", ".js", ".mjs", ".cjs"}


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    rule: str
    severity: str
    message: str


class PythonCrashVisitor(ast.NodeVisitor):
    def __init__(self, path: str) -> None:
        self.path = path
        self.findings: list[Finding] = []
        self.scope_depth = 0

    def add(self, node: ast.AST, rule: str, severity: str, message: str) -> None:
        self.findings.append(Finding(self.path, getattr(node, "lineno", 1), rule, severity, message))

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.scope_depth += 1
        self.generic_visit(node)
        self.scope_depth -= 1

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.scope_depth += 1
        self.generic_visit(node)
        self.scope_depth -= 1

    def visit_Subscript(self, node: ast.Subscript) -> None:
        if self.scope_depth == 0 and isinstance(node.value, ast.Attribute):
            value = node.value
            if isinstance(value.value, ast.Name) and value.value.id == "os" and value.attr == "environ":
                self.add(node, "PY001", "high", "Module-level os.environ[...] can crash service startup when a variable is missing; prefer os.getenv plus explicit validation.")
        self.generic_visit(node)

    def visit_Raise(self, node: ast.Raise) -> None:
        exc = node.exc
        if isinstance(exc, ast.Call) and isinstance(exc.func, ast.Name) and exc.func.id == "SystemExit":
            self.add(node, "PY002", "critical", "Raising SystemExit can terminate the Amosclaud service process.")
        elif isinstance(exc, ast.Name) and exc.id == "SystemExit":
            self.add(node, "PY002", "critical", "Raising SystemExit can terminate the Amosclaud service process.")
        self.generic_visit(node)

    def visit_While(self, node: ast.While) -> None:
        if isinstance(node.test, ast.Constant) and node.test.value is True:
            has_break = any(isinstance(child, ast.Break) for child in ast.walk(node))
            if not has_break:
                self.add(node, "PY003", "high", "Unbounded while True loop has no visible break and may hang a worker or consume CPU.")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        name = _call_name(node.func)
        if name in {"sys.exit", "os._exit", "exit", "quit"}:
            self.add(node, "PY004", "critical", f"{name}() can terminate the running Amosclaud process.")
        if name in {"subprocess.run", "subprocess.call", "subprocess.check_call", "subprocess.check_output"} and not _has_keyword(node, "timeout"):
            self.add(node, "PY005", "high", f"{name}() has no timeout and can hang a request, worker, or deployment indefinitely.")
        if re.fullmatch(r"requests\.(get|post|put|patch|delete|head|options|request)", name) and not _has_keyword(node, "timeout"):
            self.add(node, "PY006", "high", f"{name}() has no timeout; a stalled upstream can exhaust Amosclaud workers.")
        if re.fullmatch(r"httpx\.(get|post|put|patch|delete|head|options|request)", name) and not _has_keyword(node, "timeout"):
            self.add(node, "PY007", "high", f"{name}() has no timeout; a stalled upstream can exhaust Amosclaud workers.")
        self.generic_visit(node)


def _call_name(node: ast.AST) -> str:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _has_keyword(node: ast.Call, name: str) -> bool:
    return any(keyword.arg == name for keyword in node.keywords)


def scan_python(path: Path, root: Path) -> list[Finding]:
    rel = path.relative_to(root).as_posix()
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return []
    try:
        tree = ast.parse(source, filename=rel)
    except SyntaxError as exc:
        return [Finding(rel, exc.lineno or 1, "PY000", "critical", f"Python syntax error: {exc.msg}")]
    visitor = PythonCrashVisitor(rel)
    visitor.visit(tree)
    return visitor.findings


JS_RULES = [
    (re.compile(r"\bprocess\.exit\s*\("), "JS001", "critical", "process.exit() can terminate the Node service process."),
    (re.compile(r"\bJSON\.parse\s*\(\s*process\.env\b"), "JS002", "high", "JSON.parse(process.env...) can crash startup on missing or malformed configuration; validate first."),
    (re.compile(r"\bwhile\s*\(\s*true\s*\)"), "JS003", "medium", "while(true) can hang a worker or consume CPU; ensure bounded exit/backoff behavior."),
]


def scan_javascript(path: Path, root: Path) -> list[Finding]:
    rel = path.relative_to(root).as_posix()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return []
    findings: list[Finding] = []
    for lineno, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith(("//", "*")):
            continue
        for pattern, rule, severity, message in JS_RULES:
            if pattern.search(line):
                findings.append(Finding(rel, lineno, rule, severity, message))
    return findings


def iter_source_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix not in TEXT_SUFFIXES:
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        if path.stat().st_size > 1_000_000:
            continue
        files.append(path)
    return files


def emit_github(findings: list[Finding]) -> None:
    for finding in findings:
        level = "error" if finding.severity == "critical" else "warning"
        msg = finding.message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        print(f"::{level} file={finding.path},line={finding.line},title=Amosclaud Crash Shield {finding.rule}::{msg}")


def node_syntax_check(path: Path, root: Path) -> list[Finding]:
    rel = path.relative_to(root).as_posix()
    try:
        proc = subprocess.run(["node", "--check", str(path)], capture_output=True, text=True, timeout=10, check=False)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    if proc.returncode == 0:
        return []
    text = (proc.stderr or proc.stdout or "Node syntax check failed").strip().splitlines()
    return [Finding(rel, 1, "JS000", "critical", text[-1][:300] if text else "Node syntax check failed")]


def main() -> int:
    parser = argparse.ArgumentParser(description="Warn about code lines likely to crash or hang Amosclaud.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--github-annotations", action="store_true")
    parser.add_argument("--json-report")
    parser.add_argument("--fail-on-critical", action="store_true")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    findings: list[Finding] = []
    for path in iter_source_files(root):
        if path.suffix == ".py":
            findings.extend(scan_python(path, root))
        else:
            findings.extend(scan_javascript(path, root))
            findings.extend(node_syntax_check(path, root))

    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    findings.sort(key=lambda item: (severity_order.get(item.severity, 9), item.path, item.line, item.rule))

    if args.github_annotations:
        emit_github(findings)
    for finding in findings:
        print(f"{finding.severity.upper():8} {finding.path}:{finding.line} {finding.rule} {finding.message}")

    if args.json_report:
        Path(args.json_report).write_text(json.dumps({"count": len(findings), "findings": [asdict(item) for item in findings]}, indent=2) + "\n", encoding="utf-8")

    critical = sum(1 for item in findings if item.severity == "critical")
    high = sum(1 for item in findings if item.severity == "high")
    print(f"Amosclaud Crash Shield: {len(findings)} finding(s), {critical} critical, {high} high.")
    return 2 if args.fail_on_critical and critical else 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Repository mapping and static evidence collection."""

from __future__ import annotations

import ast
from pathlib import Path


class CodeAnalyzer:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()

    def inspect(self) -> list[str]:
        evidence: list[str] = []
        python_files = list(self.workspace.rglob("*.py"))
        evidence.append(f"Discovered {len(python_files)} Python source files")
        parse_failures = 0
        for path in python_files[:500]:
            if any(part in {".git", ".venv", "venv", "node_modules"} for part in path.parts):
                continue
            try:
                ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
            except SyntaxError as exc:
                parse_failures += 1
                evidence.append(f"Syntax error: {path.relative_to(self.workspace)}:{exc.lineno}")
        evidence.append(f"AST parse failures: {parse_failures}")
        return evidence

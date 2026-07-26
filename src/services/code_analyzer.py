"""Repository mapping and bounded static evidence collection."""

from __future__ import annotations

import ast
import re
from pathlib import Path


class CodeAnalyzer:
    """Collect enough repository evidence for a model to propose a real repair.

    The collector is deliberately bounded and excludes credentials, generated
    content, dependency trees, and files outside the authorized workspace.
    """

    SAFE_SUFFIXES = {
        ".py",
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        ".json",
        ".toml",
        ".yml",
        ".yaml",
        ".md",
        ".sh",
        ".html",
        ".css",
    }
    IGNORED_PARTS = {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "dist",
        "build",
        "coverage",
        "data",
        "artifacts",
        "__pycache__",
    }
    SENSITIVE_NAMES = {
        ".env",
        ".env.local",
        ".env.production",
        "credentials.json",
        "secrets.json",
        "id_rsa",
        "id_ed25519",
    }
    MAX_CONTEXT_FILES = 8
    MAX_FILE_BYTES = 100_000
    MAX_SNIPPET_CHARS = 4_500
    MAX_FILE_MAP = 80

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()

    def inspect(self, objective: str = "") -> list[str]:
        evidence: list[str] = []
        python_files = list(self.workspace.rglob("*.py"))
        evidence.append(f"Discovered {len(python_files)} Python source files")
        parse_failures = 0
        for path in python_files[:500]:
            if not self._safe_candidate(path):
                continue
            try:
                ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
            except SyntaxError as exc:
                parse_failures += 1
                evidence.append(
                    f"Syntax error: {path.relative_to(self.workspace)}:{exc.lineno}"
                )
        evidence.append(f"AST parse failures: {parse_failures}")
        evidence.extend(self._repository_context(objective))
        return evidence

    def _safe_candidate(self, path: Path) -> bool:
        try:
            if path.is_symlink() or not path.is_file():
                return False
            resolved = path.resolve(strict=True)
            if resolved != self.workspace and self.workspace not in resolved.parents:
                return False
            relative = resolved.relative_to(self.workspace)
        except (OSError, RuntimeError, ValueError):
            return False
        if any(part in self.IGNORED_PARTS for part in relative.parts):
            return False
        if relative.name.lower() in self.SENSITIVE_NAMES:
            return False
        if any("secret" in part.lower() or "credential" in part.lower() for part in relative.parts):
            return False
        return resolved.suffix.lower() in self.SAFE_SUFFIXES

    @staticmethod
    def _objective_terms(objective: str) -> set[str]:
        ignored = {
            "this",
            "that",
            "with",
            "from",
            "have",
            "into",
            "your",
            "repository",
            "please",
            "issue",
            "error",
            "failure",
            "failing",
            "repair",
            "fix",
            "test",
            "tests",
        }
        return {
            token
            for token in re.findall(r"[a-zA-Z0-9_./-]+", objective.lower())
            if len(token) >= 4 and token not in ignored
        }

    def _repository_context(self, objective: str) -> list[str]:
        candidates: list[tuple[int, str, str]] = []
        file_map: list[str] = []
        terms = self._objective_terms(objective)
        preferred_names = {
            "pyproject.toml",
            "package.json",
            "requirements.txt",
            "pytest.ini",
            "tox.ini",
            "setup.cfg",
            "app.py",
            "main.py",
            "readme.md",
        }

        for path in sorted(self.workspace.rglob("*")):
            if not self._safe_candidate(path):
                continue
            relative = path.relative_to(self.workspace).as_posix()
            if len(file_map) < self.MAX_FILE_MAP:
                file_map.append(relative)
            try:
                if path.stat().st_size > self.MAX_FILE_BYTES:
                    continue
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            lowered_path = relative.lower()
            lowered_text = text.lower()
            score = 1 if path.name.lower() in preferred_names else 0
            for term in terms:
                if term in lowered_path:
                    score += 8
                if term in lowered_text:
                    score += min(4, lowered_text.count(term))
            if relative.startswith("tests/") and any(term in lowered_path for term in terms):
                score += 4
            if score:
                candidates.append((score, relative, text))

        evidence: list[str] = []
        if file_map:
            evidence.append("Repository file map (bounded):\n" + "\n".join(file_map))
        candidates.sort(key=lambda item: (-item[0], item[1]))
        for _score, relative, text in candidates[: self.MAX_CONTEXT_FILES]:
            snippet = text[: self.MAX_SNIPPET_CHARS]
            if len(text) > len(snippet):
                snippet += "\n... [truncated by Amosclaud context bound]"
            evidence.append(f"Repository file `{relative}`:\n{snippet}")
        if not candidates:
            evidence.append(
                "No objective-matched source file was selected; use the bounded file map "
                "and request a more specific failure location before changing code."
            )
        return evidence

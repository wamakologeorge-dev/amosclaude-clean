"""Zero-config repository context compression and deterministic guardrails."""

from __future__ import annotations

import ast
import json
import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

import yaml

EXCLUDED_DIRECTORIES = {
    ".git",
    ".hg",
    ".svn",
    ".mypy_cache",
    ".next",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "env",
    "node_modules",
    "target",
    "vendor",
    "venv",
}

TEXT_SUFFIXES = {
    ".bash",
    ".c",
    ".cfg",
    ".cpp",
    ".cs",
    ".css",
    ".go",
    ".h",
    ".hpp",
    ".html",
    ".ini",
    ".java",
    ".js",
    ".json",
    ".jsx",
    ".md",
    ".php",
    ".py",
    ".rb",
    ".rs",
    ".rst",
    ".sh",
    ".sql",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
}

PRIORITY_FILENAMES = {
    "dockerfile",
    "makefile",
    "package.json",
    "pyproject.toml",
    "readme.md",
    "requirements.txt",
}

SENSITIVE_EXACT_NAMES = {
    ".env",
    "credentials",
    "credentials.json",
    "id_dsa",
    "id_ed25519",
    "id_rsa",
    "secrets.json",
}

SENSITIVE_SUFFIXES = {
    ".key",
    ".p12",
    ".pfx",
    ".pem",
}

MERGE_MARKER = re.compile(r"^(<<<<<<< |=======|>>>>>>> )", re.MULTILINE)
WORD = re.compile(r"[A-Za-z0-9_./-]{2,}")


@dataclass(frozen=True)
class Candidate:
    path: Path
    relative: str
    source: str
    score: int


def objective_terms(objective: str) -> tuple[str, ...]:
    """Return stable lowercase search terms from one engineering objective."""

    ignored = {
        "and",
        "for",
        "from",
        "into",
        "repository",
        "the",
        "this",
        "with",
    }
    terms = {
        token.lower().strip("./-")
        for token in WORD.findall(objective)
        if token.lower().strip("./-") not in ignored
    }
    return tuple(sorted(term for term in terms if len(term) >= 2))


def is_sensitive_path(path: Path) -> bool:
    """Return whether a file must never be read by the zero-config scanner."""

    name = path.name.lower()
    if name in SENSITIVE_EXACT_NAMES or name.startswith(".env."):
        return True
    if path.suffix.lower() in SENSITIVE_SUFFIXES:
        return True
    return any(part.lower() in {"secrets", ".secrets"} for part in path.parts)


def _is_supported(path: Path) -> bool:
    return path.name.lower() in PRIORITY_FILENAMES or path.suffix.lower() in TEXT_SUFFIXES


def iter_repository_paths(root: Path) -> Iterator[Path]:
    """Yield repository files while pruning dependency and build directories."""

    for directory, names, files in os.walk(root):
        names[:] = sorted(name for name in names if name not in EXCLUDED_DIRECTORIES)
        directory_path = Path(directory)
        for name in sorted(files):
            path = directory_path / name
            if path.is_symlink() or not path.is_file():
                continue
            yield path


def iter_candidate_paths(root: Path) -> Iterator[Path]:
    """Yield supported repository files in deterministic order."""

    for path in iter_repository_paths(root):
        if _is_supported(path):
            yield path


def sensitive_paths(root: Path) -> tuple[str, ...]:
    """Return sensitive repository paths without reading their contents."""

    return tuple(
        sorted(
            path.relative_to(root).as_posix()
            for path in iter_repository_paths(root)
            if is_sensitive_path(path.relative_to(root))
        )
    )


def _read_text(path: Path, *, maximum_bytes: int = 512_000) -> str | None:
    try:
        if path.stat().st_size > maximum_bytes:
            return None
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _score(relative: str, source: str, terms: Iterable[str]) -> int:
    path_text = relative.lower()
    source_text = source.lower()
    score = 0
    for term in terms:
        score += min(path_text.count(term), 3) * 10
        score += min(source_text.count(term), 5) * 3
    name = Path(relative).name.lower()
    if name in PRIORITY_FILENAMES:
        score += 5
    if Path(relative).suffix.lower() in {".py", ".js", ".ts", ".go", ".rs"}:
        score += 2
    score += max(0, 4 - relative.count("/"))
    return score


def _line_indexes(source: str, terms: tuple[str, ...]) -> tuple[int, ...]:
    lines = source.splitlines()
    matches = [
        index
        for index, line in enumerate(lines)
        if terms and any(term in line.lower() for term in terms)
    ]
    if matches:
        return tuple(matches[:8])
    return tuple(index for index, line in enumerate(lines) if line.strip())[:3]


def _snippet_lines(source: str, terms: tuple[str, ...]) -> tuple[tuple[int, str], ...]:
    lines = source.splitlines()
    selected: set[int] = set()
    for index in _line_indexes(source, terms):
        selected.update(range(max(0, index - 2), min(len(lines), index + 3)))
    return tuple((index + 1, lines[index]) for index in sorted(selected))


def compress_context(
    root: Path,
    objective: str,
    *,
    max_lines: int = 50,
    max_files: int = 8,
) -> dict:
    """Return the smallest deterministic repository context for an objective."""

    root = root.expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError("repository root must be a directory")
    if max_lines < 1 or max_lines > 500:
        raise ValueError("max_lines must be between 1 and 500")
    if max_files < 1 or max_files > 50:
        raise ValueError("max_files must be between 1 and 50")

    terms = objective_terms(objective)
    candidates: list[Candidate] = []
    sensitive = list(sensitive_paths(root))
    scanned = 0

    for path in iter_candidate_paths(root):
        relative = path.relative_to(root).as_posix()
        source = _read_text(path)
        if source is None:
            continue
        scanned += 1
        candidates.append(
            Candidate(
                path=path,
                relative=relative,
                source=source,
                score=_score(relative, source, terms),
            )
        )

    candidates.sort(key=lambda item: (-item.score, item.relative.lower()))
    snippets: list[dict] = []
    remaining = max_lines

    for candidate in candidates[: max_files * 3]:
        if remaining <= 0 or len(snippets) >= max_files:
            break
        lines = list(_snippet_lines(candidate.source, terms))
        if not lines:
            continue
        lines = lines[:remaining]
        snippets.append(
            {
                "path": candidate.relative,
                "score": candidate.score,
                "lines": [{"number": number, "text": text} for number, text in lines],
            }
        )
        remaining -= len(lines)

    selected_lines = max_lines - remaining
    selected_characters = sum(
        len(line["text"]) for snippet in snippets for line in snippet["lines"]
    )
    return {
        "root": str(root),
        "objective": objective,
        "terms": list(terms),
        "scanned_files": scanned,
        "selected_files": len(snippets),
        "selected_lines": selected_lines,
        "estimated_tokens": max(1, selected_characters // 4) if selected_lines else 0,
        "snippets": snippets,
        "excluded_directories": sorted(EXCLUDED_DIRECTORIES),
        "sensitive_files_skipped": sorted(sensitive),
    }


def _validation_failure(path: str, check: str, detail: str) -> dict:
    return {"path": path, "check": check, "status": "failed", "detail": detail}


def _validation_success(path: str, check: str) -> dict:
    return {"path": path, "check": check, "status": "passed"}


def validate_repository(root: Path, *, maximum_files: int = 2_000) -> dict:
    """Run fast, deterministic syntax and configuration checks without an AI model."""

    root = root.expanduser().resolve(strict=True)
    checks: list[dict] = []
    sensitive = list(sensitive_paths(root))
    validated = 0
    truncated = False

    for path in iter_candidate_paths(root):
        relative_path = path.relative_to(root)
        relative = relative_path.as_posix()
        if validated >= maximum_files:
            truncated = True
            break
        source = _read_text(path)
        if source is None:
            continue
        validated += 1

        if MERGE_MARKER.search(source):
            checks.append(
                _validation_failure(
                    relative,
                    "merge-markers",
                    "unresolved merge marker",
                )
            )
            continue

        suffix = path.suffix.lower()
        try:
            if suffix == ".py":
                ast.parse(source, filename=relative)
                checks.append(_validation_success(relative, "python-ast"))
            elif suffix == ".json":
                json.loads(source)
                checks.append(_validation_success(relative, "json"))
            elif suffix in {".yaml", ".yml"}:
                yaml.safe_load(source)
                checks.append(_validation_success(relative, "yaml"))
            elif suffix == ".toml":
                tomllib.loads(source)
                checks.append(_validation_success(relative, "toml"))
        except (SyntaxError, json.JSONDecodeError, yaml.YAMLError, tomllib.TOMLDecodeError) as exc:
            checks.append(
                _validation_failure(
                    relative,
                    {
                        ".py": "python-ast",
                        ".json": "json",
                        ".yaml": "yaml",
                        ".yml": "yaml",
                        ".toml": "toml",
                    }[suffix],
                    str(exc),
                )
            )

    failures = [check for check in checks if check["status"] == "failed"]
    return {
        "root": str(root),
        "passed": not failures,
        "validated_files": validated,
        "checks_run": len(checks),
        "failures": failures,
        "checks": checks,
        "truncated": truncated,
        "sensitive_files_skipped": sorted(sensitive),
    }


def quickcheck(
    root: Path,
    objective: str,
    *,
    max_lines: int = 50,
    max_files: int = 8,
) -> dict:
    """Build compact context and run deterministic guardrails in one call."""

    context = compress_context(
        root,
        objective,
        max_lines=max_lines,
        max_files=max_files,
    )
    guardrails = validate_repository(root)
    return {
        "version": 1,
        "status": "passed" if guardrails["passed"] else "failed",
        "context": context,
        "guardrails": guardrails,
    }

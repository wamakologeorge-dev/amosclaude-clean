"""Source discovery for ``amosclaud.src.cb``."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SourceCB:
    path: str
    language: str
    size_bytes: int


_LANGUAGE_BY_SUFFIX = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".html": "html",
    ".css": "css",
    ".json": "json",
    ".yml": "yaml",
    ".yaml": "yaml",
    ".md": "markdown",
}


def discover_sources(root: str | Path, *, max_files: int = 500) -> list[SourceCB]:
    base = Path(root).resolve()
    if not base.is_dir():
        raise ValueError(f"source root is not a directory: {base}")
    results: list[SourceCB] = []
    for path in sorted(base.rglob("*")):
        if not path.is_file() or any(part in {".git", ".venv", "node_modules", "__pycache__"} for part in path.parts):
            continue
        language = _LANGUAGE_BY_SUFFIX.get(path.suffix.lower())
        if language is None:
            continue
        results.append(SourceCB(str(path.relative_to(base)), language, path.stat().st_size))
        if len(results) >= max_files:
            break
    return results

"""Folder layout and safe corpus ingestion for the native model."""

from __future__ import annotations

import json
from pathlib import Path

from amosclaud_model.config import ModelConfig

TEXT_EXTENSIONS = {
    ".c",
    ".cc",
    ".cpp",
    ".css",
    ".go",
    ".h",
    ".html",
    ".java",
    ".js",
    ".json",
    ".jsonl",
    ".jsx",
    ".kt",
    ".md",
    ".php",
    ".py",
    ".rb",
    ".rs",
    ".sh",
    ".sql",
    ".swift",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
}
IGNORED_PARTS = {".git", ".venv", "node_modules", "dist", "build", "__pycache__", "secrets"}
MAX_FILE_BYTES = 1_000_000


def initialize(root: Path, config: ModelConfig | None = None) -> dict:
    config = config or ModelConfig()
    for relative in (
        "config",
        "datasets/raw",
        "datasets/curated",
        "datasets/eval",
        "tokenizer",
        "checkpoints",
        "checkpoints/versions",
        "logs",
        "logs/service",
        "training/jobs",
    ):
        (root / relative).mkdir(parents=True, exist_ok=True)
    config.save(root)
    manifest = root / "datasets" / "manifest.jsonl"
    manifest.touch(exist_ok=True)
    return {"root": str(root), "model": config.name, "initialized": True}


def iter_documents(root: Path, subsets: tuple[str, ...] = ("raw", "curated")):
    datasets = root / "datasets"
    for subset in subsets:
        for path in sorted((datasets / subset).rglob("*")):
            yield from _documents_in_file(path)


def _documents_in_file(path: Path):
    if not path.is_file() or path.name == "manifest.jsonl":
        return
    if (
        any(part in IGNORED_PARTS for part in path.parts)
        or path.suffix.lower() not in TEXT_EXTENSIONS
    ):
        return
    if path.stat().st_size > MAX_FILE_BYTES:
        return
    text = path.read_text(encoding="utf-8", errors="ignore").strip()
    if not text:
        return
    if path.suffix.lower() == ".jsonl":
        for line in text.splitlines():
            try:
                item = json.loads(line)
                value = item.get("text") or item.get("content") or item.get("completion")
                if value:
                    yield str(value)
            except json.JSONDecodeError:
                continue
    else:
        yield text


def import_folder(root: Path, source: Path, license_name: str = "unverified") -> dict:
    """Copy only safe text/code files into a named raw-dataset folder."""
    import hashlib
    import shutil

    source = source.expanduser().resolve()
    if not source.is_dir():
        raise ValueError("Dataset source must be a directory")
    destination = root / "datasets" / "raw" / source.name
    copied = 0
    content_hash = hashlib.sha256()
    for path in sorted(source.rglob("*")):
        if not path.is_file() or any(part in IGNORED_PARTS for part in path.parts):
            continue
        if path.suffix.lower() not in TEXT_EXTENSIONS or path.stat().st_size > MAX_FILE_BYTES:
            continue
        relative = path.relative_to(source)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        content_hash.update(str(relative).encode())
        content_hash.update(path.read_bytes())
        copied += 1
    record = {
        "source": source.name,
        "dataset": destination.name,
        "files": copied,
        "license": license_name.strip() or "unverified",
        "content_sha256": content_hash.hexdigest(),
    }
    record["id"] = hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()[:16]
    with (root / "datasets" / "manifest.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")
    return record

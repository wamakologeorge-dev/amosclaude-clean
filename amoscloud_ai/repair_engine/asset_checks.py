"""Safer HTML asset checks for the Amosclaud repair engine.

Root-relative web URLs are application URLs, not host filesystem paths. The
FastAPI application serves ``/static/<name>`` from the repository's ``web/``
directory and serves root files such as ``/manifest.webmanifest`` from that same
directory. This module resolves those deployed URL mappings before reporting a
missing local asset.
"""

from __future__ import annotations

from pathlib import Path

from .core import Finding, LOCAL_ASSET_PATTERN, Severity, relative


def _root_relative_candidates(root: Path, asset: str) -> list[Path]:
    route = asset.lstrip("/")
    candidates: list[Path] = []

    # Keep compatibility with repositories that really contain a root-level
    # static directory.
    candidates.append((root / route).resolve())

    web_root = root / "web"
    if route.startswith("static/"):
        candidates.append((web_root / route.removeprefix("static/")).resolve())
    else:
        candidates.append((web_root / route).resolve())

    return candidates


def safer_local_assets(doctor: object, path: Path) -> list[Finding]:
    """Inspect HTML references using the application's deployed URL mapping."""
    root = getattr(doctor, "root")
    rel = relative(path, root)
    text = path.read_text(encoding="utf-8")
    findings: list[Finding] = []

    for asset in LOCAL_ASSET_PATTERN.findall(text):
        if asset.startswith("/"):
            route = asset.lstrip("/")
            if not route or Path(route).suffix == "":
                continue
            candidates = _root_relative_candidates(root, asset)
        else:
            candidates = [(path.parent / asset).resolve()]

        safe_candidates: list[Path] = []
        for candidate in candidates:
            try:
                candidate.relative_to(root)
            except ValueError:
                continue
            safe_candidates.append(candidate)

        if not safe_candidates:
            findings.append(
                Finding(
                    "asset-outside-root",
                    f"Local asset escapes repository root: {asset}",
                    Severity.CRITICAL,
                    rel,
                )
            )
            continue

        if not any(candidate.exists() for candidate in safe_candidates):
            findings.append(
                Finding(
                    "missing-local-asset",
                    f"Referenced local asset is missing: {asset}",
                    Severity.CRITICAL,
                    rel,
                )
            )

    return findings

"""Safer HTML asset checks for the Amosclaud repair engine.

Root-relative web URLs (for example ``/static/app.css`` and ``/api/v1``)
are application URLs, not filesystem paths that escape the repository.
Only relative paths that genuinely resolve outside the checkout are reported as
``asset-outside-root``.
"""

from __future__ import annotations

from pathlib import Path

from .core import Finding, LOCAL_ASSET_PATTERN, Severity, relative


def safer_local_assets(doctor: object, path: Path) -> list[Finding]:
    """Inspect HTML references without misclassifying root-relative web URLs."""
    root = getattr(doctor, "root")
    rel = relative(path, root)
    text = path.read_text(encoding="utf-8")
    findings: list[Finding] = []

    for asset in LOCAL_ASSET_PATTERN.findall(text):
        # A leading slash is a URL rooted at the deployed application, not an
        # absolute host filesystem path. Route-like URLs do not represent files
        # and therefore should not be checked for local existence.
        if asset.startswith("/"):
            route = asset.lstrip("/")
            if not route or Path(route).suffix == "":
                continue
            target = (root / route).resolve()
        else:
            target = (path.parent / asset).resolve()

        try:
            target.relative_to(root)
        except ValueError:
            findings.append(
                Finding(
                    "asset-outside-root",
                    f"Local asset escapes repository root: {asset}",
                    Severity.CRITICAL,
                    rel,
                )
            )
            continue

        if not target.exists():
            findings.append(
                Finding(
                    "missing-local-asset",
                    f"Referenced local asset is missing: {asset}",
                    Severity.CRITICAL,
                    rel,
                )
            )

    return findings

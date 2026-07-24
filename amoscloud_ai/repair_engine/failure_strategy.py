from __future__ import annotations

import re
from pathlib import Path

from .core import Repair

_MISSING_MODULE = re.compile(
    r"(?:ModuleNotFoundError:\s*)?No module named\s+['\"]?([A-Za-z0-9_.-]+)['\"]?",
    re.IGNORECASE,
)

# Deterministic allowlist. These development/test dependencies have
# unambiguous package names and are safe to append to an existing pip command.
_MODULE_PACKAGES = {
    "pytest": "pytest",
    "yaml": "pyyaml",
}


def missing_packages(evidence: str) -> list[str]:
    packages: list[str] = []
    for module in _MISSING_MODULE.findall(evidence):
        root_module = module.split(".", 1)[0].lower()
        package = _MODULE_PACKAGES.get(root_module)
        if package and package not in packages:
            packages.append(package)
    return packages


def apply_ci_failure_strategy(root: Path, evidence: str) -> list[Repair]:
    """Apply a narrowly allowlisted repair derived from real CI evidence.

    This is a repair strategy inside Amosclaud-Fixer, not another fixer. It
    never guesses arbitrary packages or edits application imports. It only
    updates an existing workflow pip-install command when that same workflow
    invokes the missing module.
    """

    root = root.resolve()
    packages = missing_packages(evidence)
    if not packages:
        return []

    workflow_root = root / ".github" / "workflows"
    if not workflow_root.is_dir():
        return []

    repairs: list[Repair] = []
    workflow_paths = sorted((*workflow_root.glob("*.yml"), *workflow_root.glob("*.yaml")))
    for path in workflow_paths:
        text = path.read_text(encoding="utf-8")
        lowered = text.lower()
        selected = [
            package
            for package in packages
            if f"python -m {package}" in lowered
            or re.search(rf"(?m)^\s*run:\s*{re.escape(package)}(?:\s|$)", lowered)
        ]
        if not selected:
            continue

        lines = text.splitlines(keepends=True)
        changed = False
        for index, line in enumerate(lines):
            if "python -m pip install" not in line and not re.search(r"\bpip\s+install\b", line):
                continue
            existing = line.lower()
            additions = [
                package
                for package in selected
                if not re.search(rf"\b{re.escape(package)}\b", existing)
            ]
            if not additions:
                continue
            newline = "\n" if line.endswith("\n") else ""
            lines[index] = line.rstrip("\n") + " " + " ".join(additions) + newline
            changed = True
            break

        rel = path.relative_to(root).as_posix()
        if changed:
            path.write_text("".join(lines), encoding="utf-8")
        repairs.append(
            Repair(
                "ci-missing-python-module",
                rel,
                "add allowlisted missing CI package(s): " + ", ".join(selected),
                changed,
            )
        )

    return repairs

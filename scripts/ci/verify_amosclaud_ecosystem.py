#!/usr/bin/env python3
"""Verify the repository-level Amosclaud ecosystem and root cleanliness."""

from __future__ import annotations

import argparse
import fnmatch
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

EXPECTED_COMMENT = ".Amosclaud/main clean_100%"


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"Manifest does not exist: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Manifest is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("Manifest root must be a JSON object")
    return payload


def tracked_root_entry_names(root: Path) -> set[str] | None:
    """Return top-level names represented by Git-tracked paths.

    Runtime caches, test reports, and other ignored files may exist while the
    verifier runs. They are not repository artifacts unless Git tracks a path
    beneath that top-level entry. When Git metadata is unavailable, return
    ``None`` so the caller safely falls back to inspecting the filesystem.
    """

    try:
        result = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=root,
            capture_output=True,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None

    names: set[str] = set()
    for raw in result.stdout.split(b"\0"):
        if not raw:
            continue
        relative = Path(raw.decode("utf-8", errors="surrogateescape"))
        if relative.parts:
            names.add(relative.parts[0])
    return names


def verify(root: Path, manifest_path: Path) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    manifest = load_manifest(manifest_path)

    if manifest.get("root") != ".Amosclaud/main":
        errors.append("manifest root must be .Amosclaud/main")
    if manifest.get("completion_comment") != EXPECTED_COMMENT:
        errors.append(f"completion_comment must be exactly {EXPECTED_COMMENT!r}")

    required_paths = manifest.get("required_paths", [])
    if not isinstance(required_paths, list) or not required_paths:
        errors.append("required_paths must be a non-empty list")
        required_paths = []
    for relative in required_paths:
        if not isinstance(relative, str) or not relative.strip():
            errors.append("required_paths contains an invalid path")
            continue
        if not (root / relative).exists():
            errors.append(f"required ecosystem path is missing: {relative}")

    subsystems = manifest.get("subsystems", {})
    if not isinstance(subsystems, dict) or not subsystems:
        errors.append("subsystems must be a non-empty object")
        subsystems = {}
    for name, config in subsystems.items():
        if not isinstance(config, dict):
            errors.append(f"subsystem {name!r} must be an object")
            continue
        relative = config.get("path")
        if not isinstance(relative, str) or not relative:
            errors.append(f"subsystem {name!r} has no valid path")
        elif not (root / relative).exists():
            errors.append(f"subsystem {name!r} is disconnected: {relative}")
        if not str(config.get("purpose", "")).strip():
            errors.append(f"subsystem {name!r} has no purpose")

    runtime = str(manifest.get("canonical_runtime", "")).strip()
    if ":" not in runtime:
        errors.append("canonical_runtime must use module:object syntax")
    else:
        module_name, object_name = runtime.split(":", 1)
        module_path = root / (module_name.replace(".", "/") + ".py")
        if not module_path.is_file():
            errors.append(f"canonical runtime module is missing: {module_path.relative_to(root)}")
        if not object_name.isidentifier():
            errors.append("canonical runtime object is not a valid identifier")

    cli_package = str(manifest.get("canonical_cli_package", "")).strip()
    if not cli_package or not (root / cli_package).is_dir():
        errors.append(f"canonical CLI package is missing: {cli_package or '<empty>'}")

    forbidden_names = set(manifest.get("forbidden_root_files", []))
    forbidden_globs = manifest.get("forbidden_root_globs", [])
    forbidden_directories = set(manifest.get("forbidden_root_directories", []))

    root_entries = sorted(root.iterdir(), key=lambda item: item.name.casefold())
    tracked_names = tracked_root_entry_names(root)

    def is_repository_entry(entry: Path) -> bool:
        return tracked_names is None or entry.name in tracked_names

    forbidden_found: list[str] = []
    for entry in root_entries:
        if not is_repository_entry(entry):
            continue
        if entry.is_file():
            if entry.name in forbidden_names or any(
                fnmatch.fnmatch(entry.name, pattern) for pattern in forbidden_globs
            ):
                forbidden_found.append(entry.name)
        elif entry.is_dir() and entry.name in forbidden_directories:
            forbidden_found.append(entry.name + "/")

    if forbidden_found:
        errors.append("forbidden root artifacts: " + ", ".join(forbidden_found))

    tracked_root_files = [
        entry.name for entry in root_entries if entry.is_file() and is_repository_entry(entry)
    ]
    if len(tracked_root_files) > 80:
        warnings.append(
            "repository root remains broad; migrate legacy source and documentation "
            "in focused follow-up PRs after dependency mapping"
        )

    return {
        "schema_version": 1,
        "status": "clean" if not errors else "failed",
        "completion_comment": EXPECTED_COMMENT,
        "manifest": str(manifest_path.relative_to(root)),
        "canonical_runtime": runtime,
        "subsystems_checked": sorted(subsystems),
        "required_paths_checked": len(required_paths),
        "root_files_observed": len(tracked_root_files),
        "errors": errors,
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest",
        default=".Amosclaud/main/ecosystem.json",
        help="Path to the ecosystem manifest",
    )
    parser.add_argument("--report", help="Optional JSON report output path")
    args = parser.parse_args()

    root = Path.cwd().resolve()
    manifest_path = (root / args.manifest).resolve()
    try:
        report = verify(root, manifest_path)
    except ValueError as exc:
        report = {
            "schema_version": 1,
            "status": "failed",
            "completion_comment": EXPECTED_COMMENT,
            "errors": [str(exc)],
            "warnings": [],
        }

    rendered = json.dumps(report, indent=2, sort_keys=True)
    print(rendered)
    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(rendered + "\n", encoding="utf-8")
    return 0 if report["status"] == "clean" else 1


if __name__ == "__main__":
    sys.exit(main())

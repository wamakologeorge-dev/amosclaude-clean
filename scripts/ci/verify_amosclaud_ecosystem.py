#!/usr/bin/env python3
"""Verify the repository-level Amosclaud ecosystem and root cleanliness."""

from __future__ import annotations

import argparse
import fnmatch
import json
import sys
from pathlib import Path
from typing import Any

EXPECTED_COMMENT = ".Amosclaud/main clean_100%"
REQUIRED_EXTERNAL_SERVICES = {"github", "railway", "redis", "mysql"}
ALLOWED_STATUSES = {"active", "configured", "provisioned", "planned"}


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


def _validate_status(
    category: str,
    name: str,
    raw_status: object,
    errors: list[str],
) -> str:
    status = str(raw_status or "").strip().lower()
    if status not in ALLOWED_STATUSES:
        errors.append(
            f"{category} {name!r} has invalid status {status or '<empty>'!r}"
        )
    return status


def _validate_environment_names(
    service_name: str,
    raw_names: object,
    errors: list[str],
) -> list[str]:
    if not isinstance(raw_names, list) or not raw_names:
        errors.append(
            f"external service {service_name!r} must define required_environment"
        )
        return []

    names: list[str] = []
    for value in raw_names:
        if not isinstance(value, str) or not value.strip():
            errors.append(
                f"external service {service_name!r} has an invalid environment name"
            )
            continue
        name = value.strip()
        if not name.replace("_", "").isalnum() or name.upper() != name:
            errors.append(
                f"external service {service_name!r} has a non-canonical "
                f"environment name: {name}"
            )
        names.append(name)

    if len(names) != len(set(names)):
        errors.append(
            f"external service {service_name!r} contains duplicate environment names"
        )
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

    external_services = manifest.get("external_services", {})
    if not isinstance(external_services, dict) or not external_services:
        errors.append("external_services must be a non-empty object")
        external_services = {}
    missing_services = REQUIRED_EXTERNAL_SERVICES.difference(external_services)
    if missing_services:
        errors.append(
            "required external services are missing: "
            + ", ".join(sorted(missing_services))
        )

    environment_contract: dict[str, list[str]] = {}
    external_service_statuses: dict[str, str] = {}
    for name, config in external_services.items():
        if not isinstance(config, dict):
            errors.append(f"external service {name!r} must be an object")
            continue
        if not str(config.get("purpose", "")).strip():
            errors.append(f"external service {name!r} has no purpose")
        external_service_statuses[name] = _validate_status(
            "external service",
            name,
            config.get("status"),
            errors,
        )
        environment_contract[name] = _validate_environment_names(
            name,
            config.get("required_environment"),
            errors,
        )

    known_nodes = set(subsystems) | set(external_services)
    connections = manifest.get("connections", [])
    if not isinstance(connections, list) or not connections:
        errors.append("connections must be a non-empty list")
        connections = []

    connection_keys: set[tuple[str, str, str]] = set()
    connection_statuses: dict[str, int] = {
        status: 0 for status in sorted(ALLOWED_STATUSES)
    }
    for index, connection in enumerate(connections):
        if not isinstance(connection, dict):
            errors.append(f"connection {index} must be an object")
            continue
        source = str(connection.get("from", "")).strip()
        target = str(connection.get("to", "")).strip()
        protocol = str(connection.get("protocol", "")).strip()
        status = _validate_status(
            "connection",
            str(index),
            connection.get("status"),
            errors,
        )
        if status in connection_statuses:
            connection_statuses[status] += 1
        if source not in known_nodes:
            errors.append(
                f"connection {index} has an unknown source: {source or '<empty>'}"
            )
        if target not in known_nodes:
            errors.append(
                f"connection {index} has an unknown target: {target or '<empty>'}"
            )
        if source and target and source == target:
            errors.append(f"connection {index} cannot connect a node to itself: {source}")
        if not protocol:
            errors.append(f"connection {index} has no protocol")
        key = (source, target, protocol)
        if key in connection_keys:
            errors.append(f"connection {index} duplicates an earlier connection: {key}")
        connection_keys.add(key)

    connected_nodes = {
        node
        for source, target, _protocol in connection_keys
        for node in (source, target)
        if node
    }
    disconnected_nodes = known_nodes.difference(connected_nodes)
    if disconnected_nodes:
        errors.append(
            "ecosystem nodes have no registered connection: "
            + ", ".join(sorted(disconnected_nodes))
        )

    planned_connections = connection_statuses.get("planned", 0)
    if planned_connections:
        warnings.append(
            f"{planned_connections} ecosystem connection(s) are registered as planned, "
            "not live"
        )

    runtime = str(manifest.get("canonical_runtime", "")).strip()
    if ":" not in runtime:
        errors.append("canonical_runtime must use module:object syntax")
    else:
        module_name, object_name = runtime.split(":", 1)
        module_path = root / (module_name.replace(".", "/") + ".py")
        if not module_path.is_file():
            errors.append(
                f"canonical runtime module is missing: {module_path.relative_to(root)}"
            )
        if not object_name.isidentifier():
            errors.append("canonical runtime object is not a valid identifier")

    cli_package = str(manifest.get("canonical_cli_package", "")).strip()
    if not cli_package or not (root / cli_package).is_dir():
        errors.append(f"canonical CLI package is missing: {cli_package or '<empty>'}")

    forbidden_names = set(manifest.get("forbidden_root_files", []))
    forbidden_globs = manifest.get("forbidden_root_globs", [])
    forbidden_directories = set(manifest.get("forbidden_root_directories", []))

    root_entries = sorted(root.iterdir(), key=lambda item: item.name.casefold())
    forbidden_found: list[str] = []
    for entry in root_entries:
        if entry.is_file():
            if entry.name in forbidden_names or any(
                fnmatch.fnmatch(entry.name, pattern) for pattern in forbidden_globs
            ):
                forbidden_found.append(entry.name)
        elif entry.is_dir() and entry.name in forbidden_directories:
            forbidden_found.append(entry.name + "/")

    if forbidden_found:
        errors.append("forbidden root artifacts: " + ", ".join(forbidden_found))

    tracked_root_files = [entry.name for entry in root_entries if entry.is_file()]
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
        "external_services_checked": sorted(external_services),
        "external_service_statuses": external_service_statuses,
        "environment_contract": environment_contract,
        "connections_checked": len(connections),
        "connection_statuses": connection_statuses,
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

"""Focused verification CLI for Amosclaud-generated repository changes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.services.runtime_exec import RuntimeExecutor


def _changed_files(path: Path) -> list[str]:
    if not path.is_file():
        return []
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def verify_repair(workspace: Path, changed_files: list[str]) -> list[dict[str, object]]:
    """Run the deterministic checks selected from the actual changed paths."""
    return RuntimeExecutor(workspace).verify(changed_files=changed_files)


def _cards(checks: list[dict[str, object]]) -> list[dict[str, str]]:
    return [
        {
            "name": str(check.get("name") or "Verification"),
            "status": "passed" if check.get("passed") else "failed",
            "detail": str(check.get("summary") or "No output")[:500],
            "command": str(check.get("command") or "")[:500],
        }
        for check in checks
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify an Amosclaud repair using the changed-file scope."
    )
    parser.add_argument("--workspace", default=".")
    parser.add_argument("--changed-files", required=True)
    parser.add_argument("--json", required=True)
    args = parser.parse_args(argv)

    workspace = Path(args.workspace).resolve()
    changed = _changed_files(Path(args.changed_files))
    if not changed:
        raise SystemExit("No changed files were supplied for verification")

    checks = verify_repair(workspace, changed)
    Path(args.json).write_text(
        json.dumps(_cards(checks), indent=2),
        encoding="utf-8",
    )

    for check in checks:
        print(f"## {check.get('name', 'Verification')}")
        print(f"Command: {check.get('command', '')}")
        print(f"Passed: {bool(check.get('passed'))}")
        output = str(check.get("output") or "")
        if output:
            print(output)

    return 0 if checks and all(check.get("passed") for check in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())

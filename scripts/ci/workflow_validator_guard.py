#!/usr/bin/env python3
"""Fail the build when GitHub would refuse a workflow file.

AMOSCLAUD-TOOL-SOVEREIGNTY-POLICY:v1 -- this guard uses Amosclaud's own
workflow validator instead of an external linter.

A workflow GitHub cannot load produces a run with zero jobs and no
annotations. Nothing else in CI can see that, because the file never reaches a
runner. This guard catches it on the pull request instead.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Load the validator straight from its file rather than importing
# ``amosclaud_bot.workflow_validator``. Importing through the package would run
# ``amosclaud_bot/__init__.py``, which pulls in the whole bot and FastAPI. This
# guard runs in the fast pull-request lane, whose dependency set is PyYAML and a
# formatter -- no FastAPI. Going through the package would crash the gate.
_VALIDATOR_PATH = REPO_ROOT / "amosclaud_bot" / "workflow_validator.py"
_spec = importlib.util.spec_from_file_location("amosclaud_workflow_validator", _VALIDATOR_PATH)
if _spec is None or _spec.loader is None:  # pragma: no cover - defensive
    raise SystemExit(f"cannot load workflow validator from {_VALIDATOR_PATH}")
_validator = importlib.util.module_from_spec(_spec)
# Register before executing: dataclasses resolves field types through
# ``sys.modules[cls.__module__]``, which is absent for a bare path load.
sys.modules[_spec.name] = _validator
_spec.loader.exec_module(_validator)
validate_directory = _validator.validate_directory


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        default=str(Path(__file__).resolve().parents[2]),
        help="repository root to scan",
    )
    args = parser.parse_args(argv)

    findings = validate_directory(Path(args.root))
    if not findings:
        print("Amosclaud workflow validator: all workflow files are valid.")
        return 0

    print(f"Amosclaud workflow validator found {len(findings)} problem(s):")
    for finding in findings:
        print(f"  {finding.format()}")
    print(
        "\nGitHub would reject these files before running any job, "
        "so the failure would be invisible in CI logs."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

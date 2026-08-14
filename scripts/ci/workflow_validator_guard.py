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
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from amosclaud_bot.workflow_validator import validate_directory  # noqa: E402


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

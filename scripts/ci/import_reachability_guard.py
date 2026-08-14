#!/usr/bin/env python3
"""Fail the build when a CI lane runs code its dependencies cannot import.

AMOSCLAUD-TOOL-SOVEREIGNTY-POLICY:v1

A lean lane installs a small dependency set and then runs a script. If that
script reaches an import the lane does not install, the job dies before doing
any work -- and no test suite can predict it, because suites run where
everything is installed.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from amosclaud_ci.import_reachability import analyse, parse_requirements  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requirements", required=True, help="dependency file the lane installs")
    parser.add_argument("--entrypoint", action="append", default=[], help="script the lane runs")
    parser.add_argument("--root", default=".", help="repository root")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    declared = parse_requirements(Path(args.requirements).resolve())
    findings = []
    for entry in args.entrypoint:
        findings.extend(analyse(Path(entry).resolve(), declared, root))

    if not findings:
        checked = ", ".join(args.entrypoint) or "nothing"
        print(f"Import reachability clean: {checked} runs under {args.requirements}.")
        return 0

    print(f"Import reachability found {len(findings)} problem(s):")
    for finding in findings:
        print(f"  {finding.format()}")
    print(
        "\nThese jobs would fail at import time, before running any step, "
        "and a full-dependency test run cannot reproduce it."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

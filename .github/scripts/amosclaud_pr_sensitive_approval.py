#!/usr/bin/env python3
"""Expose the sensitive-data approval state for a pull-request repair."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[1]
for value in (str(SCRIPT_DIR), str(ROOT)):
    if value not in sys.path:
        sys.path.insert(0, value)

from amosclaud_fork_pr_route import pull_request_files, sensitive_approval_state
from amosclaud_bot.approval_gate_v2 import _high_risk_files


def write_outputs(values: dict[str, str | bool]) -> None:
    output_path = os.getenv("GITHUB_OUTPUT")
    lines = []
    for key, value in values.items():
        if isinstance(value, bool):
            rendered = "true" if value else "false"
        else:
            rendered = value
        lines.append(f"{key}={rendered}")
    text = "\n".join(lines) + "\n"
    if output_path:
        with Path(output_path).open("a", encoding="utf-8") as output:
            output.write(text)
    else:
        print(text, end="")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--pull-request-number", default="")
    parser.add_argument("--token", required=True)
    args = parser.parse_args()

    if not args.pull_request_number:
        write_outputs(
            {
                "sensitive_detected": False,
                "approved": False,
                "approval_issue_number": "",
            }
        )
        return 0

    number = int(args.pull_request_number)
    files = pull_request_files(args.repository, number, args.token)
    sensitive = _high_risk_files(files)
    approved, approval_number = sensitive_approval_state(
        args.repository,
        number,
        args.token,
    )
    write_outputs(
        {
            "sensitive_detected": bool(sensitive),
            "approved": bool(sensitive and approved),
            "approval_issue_number": approval_number,
            "sensitive_files": ",".join(sensitive[:12]),
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

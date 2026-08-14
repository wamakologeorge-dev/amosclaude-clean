#!/usr/bin/env python3
"""Report the agent's declared level against the level it can actually prove."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from amosclaud_ci.earned_level import LevelLedger, level_report  # noqa: E402

DEFAULT_LEDGER = Path("amosclaud_ci/agent_level_ledger.jsonl")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", default=str(DEFAULT_LEDGER))
    parser.add_argument("--root", default=".")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--require-honest",
        action="store_true",
        help="exit non-zero when the declared level exceeds the earned level",
    )
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    report = level_report(LevelLedger(Path(args.ledger)), cwd=root)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        for item in report["capabilities"]:
            mark = "earned" if item["counts"] else "  no  "
            print(f"  [{mark}] {item['capability']}: {item['detail']}")
        print(
            f"\ndeclared level {report['declared_level']}, "
            f"earned level {report['earned_level']}, "
            f"unearned gap {report['unearned_gap']}"
        )
        if not report["honest"]:
            print("The declared level is not backed by evidence.")

    return 1 if args.require_honest and not report["honest"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

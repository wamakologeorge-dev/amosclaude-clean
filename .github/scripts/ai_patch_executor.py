#!/usr/bin/env python3
"""Compatibility guard for the retired external Claude patch executor.

Amosclaud patch requests now run through the native Repair Control Plane, which
selects the configured Ollama service first. This module intentionally has no
model-network client, no repository-context reader, and no commit/push authority.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence

STATUS = "NATIVE_OLLAMA_REPAIR_REQUIRED"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args, _ = build_parser().parse_known_args(argv)
    payload = {
        "schema": "amosclaud.ai-patch-executor.v2",
        "status": STATUS,
        "provider": "amosclaud-native-ollama",
        "detail": (
            "The external Claude executor is retired. Dispatch the request to "
            "amosclaud-repair-control-plane.yml, which selects Ollama first."
        ),
        "patch_applied": False,
        "commit_allowed": False,
        "push_allowed": False,
    }
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.report:
        from pathlib import Path

        path = Path(args.report)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

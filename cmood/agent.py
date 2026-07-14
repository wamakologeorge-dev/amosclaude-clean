"""Bounded, one-shot entry point used by the cmood GitHub workflow."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def process_latest_changes(repository: str, ref: str, root: Path = Path(".")) -> dict:
    files = [
        str(path.relative_to(root))
        for path in sorted(root.rglob("*"))
        if path.is_file() and ".git" not in path.parts and "__pycache__" not in path.parts
    ]
    return {
        "task": "process_latest_changes",
        "repository": repository,
        "ref": ref,
        "status": "completed",
        "files_observed": len(files),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a bounded cmood repository task")
    parser.add_argument("--task", choices=["process_latest_changes"], required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--ref", required=True)
    args = parser.parse_args(argv)
    print(json.dumps(process_latest_changes(args.repo, args.ref), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

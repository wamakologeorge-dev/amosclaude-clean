"""Command-line fast path for local Amosclaud repository checks."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from amoscloud_ai.developer_fastpath import quickcheck


def _root(value: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_dir():
        raise argparse.ArgumentTypeError("repository must be an existing directory")
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="amosclaud-quick",
        description=(
            "Compress repository context and run deterministic guardrails locally. "
            "No account, API key, model, or network connection is required."
        ),
    )
    parser.add_argument("repository", nargs="?", type=_root, default=Path.cwd())
    parser.add_argument(
        "--objective",
        default="Find the smallest relevant context and validate this repository.",
    )
    parser.add_argument("--max-lines", type=int, default=50)
    parser.add_argument("--max-files", type=int, default=8)
    parser.add_argument("--json", action="store_true", dest="json_output")
    parser.add_argument("--output", type=Path)
    return parser


def _summary(result: dict) -> str:
    context = result["context"]
    guardrails = result["guardrails"]
    paths = [snippet["path"] for snippet in context["snippets"]]
    lines = [
        "Amosclaud Quick Check",
        f"Status: {result['status']}",
        (
            f"Context: {context['selected_lines']} lines from "
            f"{context['selected_files']} files "
            f"(about {context['estimated_tokens']} tokens)"
        ),
        (
            f"Guardrails: {guardrails['checks_run']} checks across "
            f"{guardrails['validated_files']} files"
        ),
    ]
    if paths:
        lines.append("Selected: " + ", ".join(paths))
    if guardrails["failures"]:
        lines.append("Failures:")
        lines.extend(
            f"- {item['path']} [{item['check']}]: {item['detail']}"
            for item in guardrails["failures"]
        )
    if context["sensitive_files_skipped"]:
        lines.append(f"Sensitive files skipped: {len(context['sensitive_files_skipped'])}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = quickcheck(
            Path(args.repository),
            args.objective,
            max_lines=args.max_lines,
            max_files=args.max_files,
        )
    except (OSError, ValueError) as exc:
        print(f"amosclaud-quick: {exc}", file=sys.stderr)
        return 2

    payload = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    print(payload if args.json_output else _summary(result))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

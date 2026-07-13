from __future__ import annotations

import argparse
from pathlib import Path

from .lexer import AmclSyntaxError
from .runtime import AmclError, Interpreter, run_source


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="amcl",
        description="Run Amosclaud Computer Language (.amcl) programs.",
    )
    parser.add_argument("source", nargs="?", help="Path to a .amcl source file")
    parser.add_argument("-c", "--command", help="Execute AMCL source provided on the command line")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if bool(args.source) == bool(args.command):
        print("amcl: provide exactly one .amcl file or --command source")
        return 2

    if args.command is not None:
        source = args.command
    else:
        path = Path(args.source)
        if path.suffix != ".amcl":
            print("amcl: source files must use the .amcl extension")
            return 2
        try:
            source = path.read_text(encoding="utf-8")
        except OSError as exc:
            print(f"amcl: cannot read {path}: {exc}")
            return 2

    try:
        run_source(source, interpreter=Interpreter())
    except (AmclSyntaxError, AmclError) as exc:
        print(f"amcl error: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

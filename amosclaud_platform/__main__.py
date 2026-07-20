"""Run the unified Amosclaud platform command.

Examples:
    python -m amosclaud_platform start
    python -m amosclaud_platform status
    python -m amosclaud_platform doctor
    python -m amosclaud_platform stop
"""
from __future__ import annotations

import argparse
import sys

from .control import PlatformControl


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="amosclaud", description="Unified Amosclaud platform control")
    parser.add_argument(
        "command",
        choices=("start", "status", "doctor", "stop"),
        help="Platform operation to perform",
    )
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--repository-root")
    parser.add_argument("--no-amomodel", action="store_true", help="Do not power on AmoModel during start")
    return parser


def main() -> None:
    args = _parser().parse_args()
    control = PlatformControl(repository_root=args.repository_root)

    if args.command in {"status", "doctor"}:
        report = control.status() if args.command == "status" else control.doctor()
        print(report.render())
        raise SystemExit(0 if report.healthy else 1)

    if args.command == "stop":
        result = control.power_off_amomodel()
        print(result)
        return

    report = control.initialize()
    print(report.render())
    if not report.healthy:
        raise SystemExit("Amosclaud platform is degraded; run `python -m amosclaud_platform doctor`.")

    if not args.no_amomodel:
        state = control.power_on_amomodel()
        if state.get("state") not in {"ready", "busy"}:
            raise SystemExit(f"AmoModel did not become ready: {state}")

    import uvicorn

    uvicorn.run("main:app", host=args.host, port=args.port)


if __name__ == "__main__":
    main()

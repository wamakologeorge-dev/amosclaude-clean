"""Command-line interface for the Amosclaud Agent SDK.

Usage::

    amosclaud-agent status
    amosclaud-agent run "Deploy the staging environment" --wait
    amosclaud-agent run "Run tests" --mode build --branch feature/x
"""
from __future__ import annotations
import argparse
import json
from .client import AmosclaudAgentClient
from .errors import AmosclaudAgentError


def main(argv: list[str] | None = None) -> int:
    """Entry point for the ``amosclaud-agent`` CLI.

    Args:
        argv: Argument list to parse; defaults to ``sys.argv[1:]`` when ``None``.

    Returns:
        Exit code: ``0`` on success, ``1`` on any ``AmosclaudAgentError``.
    """
    parser = argparse.ArgumentParser(prog="amosclaud-agent")
    parser.add_argument("--host", default="https://www.amosclaud.com")
    parser.add_argument("--api-key")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    run = commands.add_parser("run")
    run.add_argument("objective")
    run.add_argument("--mode", default="autonomous-check")
    run.add_argument("--branch", default="main")
    run.add_argument("--wait", action="store_true")
    args = parser.parse_args(argv)
    client = AmosclaudAgentClient(base_url=args.host, api_key=args.api_key)
    try:
        if args.command == "status":
            result = client.readiness()
        elif args.wait:
            result = client.run_and_wait(args.objective, mode=args.mode, branch=args.branch)
        else:
            result = client.run(args.objective, mode=args.mode, branch=args.branch)
    except AmosclaudAgentError as error:
        parser.exit(1, f"error: {error}\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

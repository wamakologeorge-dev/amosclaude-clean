#!/usr/bin/env python3
"""Command-line entry point for Amosclaud Autonomous."""

import argparse
import sys

from cli.commands import (
    handle_fix,
    handle_jobs,
    handle_repositories,
    handle_run,
    handle_status,
    handle_sync,
)
from cli.config import CLIConfig


def add_task_arguments(parser):
    parser.add_argument("objective", help="Task for Amosclaud Autonomous")
    parser.add_argument("--repository-id", default=CLIConfig.REPOSITORY_ID or None)
    parser.add_argument("--branch", default=CLIConfig.DEFAULT_BRANCH)
    parser.add_argument("--authorize-writes", action="store_true")


def build_parser():
    parser = argparse.ArgumentParser(
        prog="amosclaud",
        description="Amosclaud Autonomous command line interface",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status", help="Read platform health")

    run_parser = subparsers.add_parser("run", help="Submit an Autonomous task")
    add_task_arguments(run_parser)
    run_parser.add_argument(
        "--mode",
        choices=["plan", "build", "test", "review", "fix", "deploy", "monitor"],
        default="plan",
    )

    fix_parser = subparsers.add_parser("fix", help="Submit an Amosclaud-Fixer task")
    add_task_arguments(fix_parser)

    sync_parser = subparsers.add_parser("sync", help="Trigger repository synchronization")
    sync_parser.add_argument("-f", "--file", required=True)
    sync_parser.add_argument(
        "-a",
        "--action",
        choices=["CREATED", "MODIFIED", "MANUAL_SYNC"],
        default="MANUAL_SYNC",
    )

    subparsers.add_parser("jobs", help="List pipeline jobs")
    subparsers.add_parser("repositories", help="List Amosclaud repositories")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    handlers = {
        "status": handle_status,
        "run": handle_run,
        "fix": handle_fix,
        "sync": handle_sync,
        "jobs": handle_jobs,
        "repositories": handle_repositories,
    }
    try:
        handlers[args.command](args)
        return 0
    except KeyboardInterrupt:
        print("\nOperation cancelled by user.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())

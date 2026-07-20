"""Command handlers for the Amosclaud Autonomous CLI."""

from __future__ import annotations

import json
import sys

from cli.client import AmosClient
from cli.config import CLIConfig

client = AmosClient()


def _print_response(response) -> None:
    print(json.dumps(response, indent=2, sort_keys=True))


def _require_success(response, label: str) -> None:
    if isinstance(response, dict) and response.get("error"):
        print(f"[-] {label}: {response.get('message', 'Unknown error')}", file=sys.stderr)
        raise SystemExit(1)


def handle_status(_args) -> None:
    print(f"Connecting to Amosclaud API at: {CLIConfig.API_URL}")
    response = client.get_status()
    _require_success(response, "Status request failed")
    _print_response(response)


def handle_run(args) -> None:
    response = client.run_agent(
        args.objective,
        mode=args.mode,
        repository_id=args.repository_id,
        branch=args.branch,
        authorized_writes=args.authorize_writes,
    )
    _require_success(response, "Autonomous task failed")
    _print_response(response)


def handle_fix(args) -> None:
    response = client.run_agent(
        args.objective,
        mode="fix",
        repository_id=args.repository_id,
        branch=args.branch,
        authorized_writes=args.authorize_writes,
    )
    _require_success(response, "Fixer task failed")
    _print_response(response)


def handle_sync(args) -> None:
    response = client.trigger_sync(args.file, args.action)
    _require_success(response, "Sync failed")
    _print_response(response)


def handle_jobs(_args) -> None:
    response = client.get_jobs()
    _require_success(response, "Failed to fetch jobs")
    _print_response(response)


def handle_repositories(_args) -> None:
    response = client.list_repositories()
    _require_success(response, "Failed to fetch repositories")
    _print_response(response)

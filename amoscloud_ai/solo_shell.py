"""Command-line shell for Amosclaud-native repository operations."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_URL = os.getenv("AMOSCLAUD_URL", "http://www.amosclaud.com/").rstrip("/")


def request(method: str, path: str, payload: dict[str, Any] | None, args: argparse.Namespace) -> Any:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if args.session:
        headers["Cookie"] = f"amos_session={args.session}"
    if args.key:
        headers["Authorization"] = f"Bearer {args.key}"
    req = urllib.request.Request(
        f"{args.url.rstrip('/')}{path}", data=data, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(req, timeout=args.timeout) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {"status": response.status}
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Amosclaud API error {error.code}: {detail}") from error
    except urllib.error.URLError as error:
        raise SystemExit(f"Amosclaud is unreachable: {error.reason}") from error


def emit(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="amosclaud-shell")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--session", default=os.getenv("AMOSCLAUD_SESSION", ""))
    parser.add_argument("--key", default=os.getenv("AMOSCLAUD_API_KEY", ""))
    parser.add_argument("--timeout", type=int, default=60)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("profile")
    profile_update = sub.add_parser("profile-set")
    profile_update.add_argument("name")

    sub.add_parser("repo-list")
    repo_create = sub.add_parser("repo-create")
    repo_create.add_argument("name")
    repo_create.add_argument("--description", default="")
    repo_create.add_argument("--public", action="store_true")

    tree = sub.add_parser("tree")
    tree.add_argument("repository_id", type=int)
    tree.add_argument("--branch", default="main")

    write = sub.add_parser("file-put")
    write.add_argument("repository_id", type=int)
    write.add_argument("path")
    write.add_argument("source", help="Local file containing the new content")
    write.add_argument("--branch", default="main")
    write.add_argument("--message", default="Update file from Amosclaud shell")

    issue = sub.add_parser("issue-create")
    issue.add_argument("repository_id", type=int)
    issue.add_argument("title")
    issue.add_argument("--body", default="")

    pull = sub.add_parser("pr-create")
    pull.add_argument("repository_id", type=int)
    pull.add_argument("title")
    pull.add_argument("head_branch")
    pull.add_argument("--base", default="main")
    pull.add_argument("--body", default="")

    merge = sub.add_parser("pr-merge")
    merge.add_argument("repository_id", type=int)
    merge.add_argument("pull_request_id", type=int)

    deploy = sub.add_parser("deployment")
    deploy.add_argument("repository_id", type=int)

    verify = sub.add_parser("verify")
    verify.add_argument("--root", default=".")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    command = args.command
    if command == "profile":
        emit(request("GET", "/api/v1/profile/me", None, args))
    elif command == "profile-set":
        emit(request("PATCH", "/api/v1/profile/me", {"name": args.name}, args))
    elif command == "repo-list":
        emit(request("GET", "/api/v1/repositories", None, args))
    elif command == "repo-create":
        emit(request("POST", "/api/v1/repositories", {
            "name": args.name,
            "description": args.description,
            "visibility": "public" if args.public else "private",
            "initialize_readme": True,
        }, args))
    elif command == "tree":
        emit(request("GET", f"/api/v1/repositories/{args.repository_id}/tree?branch={args.branch}", None, args))
    elif command == "file-put":
        content = Path(args.source).read_text(encoding="utf-8")
        emit(request("PUT", f"/api/v1/repositories/{args.repository_id}/files", {
            "path": args.path,
            "content": content,
            "branch": args.branch,
            "commit_message": args.message,
        }, args))
    elif command == "issue-create":
        emit(request("POST", f"/api/v1/repositories/{args.repository_id}/issues", {
            "title": args.title, "body": args.body
        }, args))
    elif command == "pr-create":
        emit(request("POST", f"/api/v1/repositories/{args.repository_id}/pull-requests", {
            "title": args.title,
            "body": args.body,
            "head_branch": args.head_branch,
            "base_branch": args.base,
        }, args))
    elif command == "pr-merge":
        emit(request("POST", f"/api/v1/repositories/{args.repository_id}/pull-requests/{args.pull_request_id}/merge", {}, args))
    elif command == "deployment":
        emit(request("GET", f"/api/v1/repositories/{args.repository_id}/deployment-settings", None, args))
    elif command == "verify":
        root = Path(args.root).resolve()
        commands = [
            [sys.executable, "-m", "compileall", "-q", "."],
            [sys.executable, "-m", "pytest", "-q"],
        ]
        for cmd in commands:
            result = subprocess.run(cmd, cwd=root)
            if result.returncode:
                return result.returncode
        print("Amosclaud verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

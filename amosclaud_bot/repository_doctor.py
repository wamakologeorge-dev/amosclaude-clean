"""Trusted Repository Doctor route for GitHub pull-request slash commands."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Mapping

from .bot import WRITE_ASSOCIATIONS, AmosclaudBot

SLASH_COMMANDS = {
    "/amos explain": "explain",
    "/amos scan": "scan",
    "/amos fix": "fix",
}
DOCTOR_MARKER = "<!-- amosclaud-agent-chat -->"


def parse_slash_command(payload: Mapping[str, Any]) -> tuple[str | None, int | None, bool]:
    """Return operation, pull-request number, and trusted-author status."""

    comment = payload.get("comment") or {}
    issue = payload.get("issue") or {}
    body = str(comment.get("body") or "")
    first_line = next(
        (line.strip().lower() for line in body.splitlines() if line.strip()),
        "",
    )
    operation = SLASH_COMMANDS.get(first_line)
    issue_number = issue.get("number")
    is_pull_request = bool(issue.get("pull_request"))
    association = str(comment.get("author_association") or "NONE").upper()
    trusted = association in WRITE_ASSOCIATIONS
    number = int(issue_number) if isinstance(issue_number, int) and is_pull_request else None
    return operation, number, trusted


def _load_agent_chat() -> ModuleType:
    root = Path(__file__).resolve().parents[1]
    path = root / ".github" / "scripts" / "agent_chat.py"
    spec = importlib.util.spec_from_file_location("amosclaud_agent_chat_runtime", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Repository Doctor controller could not be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _failure_comment(operation: str, run_url: str, error: Exception) -> str:
    detail = str(error).replace("`", "'")[:800]
    return "\n".join(
        [
            DOCTOR_MARKER,
            "## Amosclaud Repository Doctor",
            "",
            "**Status:** `workflow failed`",
            f"**Command:** `/amos {operation}`",
            "",
            "The Repository Doctor could not complete this command. No repair success is claimed.",
            "",
            f"**Failure:** `{detail}`",
            "",
            f"[Open the GitHub Actions run]({run_url})" if run_url else "",
            "",
            "Repository tests were not cancelled or replaced.",
        ]
    ).strip() + "\n"


def _scan_comment(run_url: str) -> str:
    return "\n".join(
        [
            "## 🐛 Amosclaud Scan Bug",
            "",
            "The read-only line scanner was dispatched for this pull request.",
            "",
            "It may capture evidence and stop its own scan, but repository tests continue independently.",
            "",
            f"[Open the command run]({run_url})" if run_url else "",
        ]
    ).strip() + "\n"


def handle_repository_doctor_command(
    bot: AmosclaudBot,
    payload: Mapping[str, Any],
) -> int | None:
    """Handle trusted `/amos` commands before pull-request code is checked out."""

    operation, pull_request_number, trusted = parse_slash_command(payload)
    if operation is None:
        return None
    if not trusted or pull_request_number is None:
        return 0

    run_url = ""
    server_url = str(payload.get("repository", {}).get("html_url") or "")
    run_id = str(payload.get("workflow_run", {}).get("id") or "")
    if server_url and run_id:
        run_url = f"{server_url}/actions/runs/{run_id}"

    if operation == "scan":
        try:
            repository = bot._request("GET", f"/repos/{bot.repository}")
            default_branch = str(repository.get("default_branch") or "main")
            bot._request(
                "POST",
                f"/repos/{bot.repository}/actions/workflows/scan.yml/dispatches",
                {
                    "ref": default_branch,
                    "inputs": {
                        "pull_request_number": str(pull_request_number),
                        "target_ref": "",
                        "dispatch_fixer": "true",
                    },
                },
            )
            bot.post_comment(pull_request_number, _scan_comment(run_url))
        except Exception as exc:
            bot.post_comment(
                pull_request_number,
                _failure_comment(operation, run_url, exc),
            )
        return 0

    try:
        controller = _load_agent_chat()
        controller.post_or_update_comment(
            bot.token,
            bot.repository,
            pull_request_number,
            "\n".join(
                [
                    DOCTOR_MARKER,
                    "## Amosclaud Repository Doctor",
                    "",
                    "**Status:** `inspecting`",
                    f"**Command:** `/amos {operation}`",
                    "",
                    "Reading the latest GitHub Actions evidence for this pull request.",
                    "",
                    "Repository tests continue independently.",
                ]
            )
            + "\n",
        )
        run = controller.latest_run_for_pull_request(
            bot.token,
            bot.repository,
            pull_request_number,
        )
        controller.run_doctor(
            token=bot.token,
            repository=bot.repository,
            run=run,
            dispatch=operation == "fix",
            comment=True,
        )
    except Exception as exc:
        try:
            controller = _load_agent_chat()
            controller.post_or_update_comment(
                bot.token,
                bot.repository,
                pull_request_number,
                _failure_comment(operation, run_url, exc),
            )
        except Exception:
            bot.post_comment(
                pull_request_number,
                _failure_comment(operation, run_url, exc),
            )
    return 0

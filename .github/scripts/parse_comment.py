#!/usr/bin/env python3
"""Parse an issue comment into the trusted Amosclaud command contract.

The helper centralizes regex extraction and command classification for GitHub
Actions. It recognizes normal ``@amosclaud`` commands, the explicit Claude patch
aliases ``patch``, ``ai-fix``, and ``claude-fix``, plus trusted structured owner
directives handled by :mod:`amosclaud_bot.owner_directives`.

The script never executes a requested action. It emits only bounded routing
metadata and writes the objective to a local file for a later trusted step.
Normal ``fix`` commands remain on Amosclaud's existing fixer path; only an
explicit Claude patch alias selects the external Claude executor.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from amosclaud_bot.bot import WRITE_ASSOCIATIONS, parse_command
from amosclaud_bot.owner_directives import normalize_owner_directive

_PATCH_ALIASES = frozenset({"patch", "ai-fix", "claude-fix"})
_BOT_NAMES = ("@amosclaud-bot", "@amosclaud")


@dataclass(frozen=True)
class ParsedComment:
    recognized: bool
    command: str | None
    objective: str
    author_association: str
    authorized_write: bool
    write_request: bool
    patch_executor: bool
    source_format: str
    issue_number: int | None
    pull_request: bool

    def public_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["objective"] = "[stored locally]" if self.objective else ""
        return payload


def _compact(value: str) -> str:
    return " ".join((value or "").strip().split())


def _explicit_patch_alias(body: str) -> tuple[str, str] | None:
    normalized = _compact(body)
    lowered = normalized.lower()
    matched = next((name for name in _BOT_NAMES if lowered.startswith(name)), None)
    if not matched:
        return None
    remainder = normalized[len(matched) :].strip()
    command, _, objective = remainder.partition(" ")
    if command.lower().strip() not in _PATCH_ALIASES:
        return None
    return "@amosclaud fix " + objective.strip(), "claude-patch-alias"


def parse_event(payload: Mapping[str, Any]) -> ParsedComment:
    """Return deterministic routing metadata for one issue-comment payload."""

    mutable = dict(payload)
    comment_value = mutable.get("comment")
    comment = dict(comment_value) if isinstance(comment_value, Mapping) else {}
    raw_body = str(comment.get("body") or "")
    association = str(comment.get("author_association") or "NONE").upper()
    source_format = "mention"

    alias = _explicit_patch_alias(raw_body)
    if alias:
        canonical_body, source_format = alias
        comment["body"] = canonical_body
        mutable["comment"] = comment
    else:
        normalized = normalize_owner_directive(mutable)
        if normalized.recognized:
            source_format = normalized.source_format
            comment = dict(mutable.get("comment") or {})
        else:
            source_format = "mention" if raw_body.strip().startswith("@") else "unrecognized"

    canonical_body = str(comment.get("body") or raw_body)
    command, objective = parse_command(canonical_body)
    recognized = command is not None
    write_request = command == "fix"
    authorized_write = write_request and association in WRITE_ASSOCIATIONS
    patch_executor = authorized_write and source_format == "claude-patch-alias"
    issue = mutable.get("issue") if isinstance(mutable.get("issue"), Mapping) else {}
    issue_number = issue.get("number")

    return ParsedComment(
        recognized=recognized,
        command=command,
        objective=_compact(objective),
        author_association=association,
        authorized_write=authorized_write,
        write_request=write_request,
        patch_executor=patch_executor,
        source_format=source_format,
        issue_number=issue_number if isinstance(issue_number, int) else None,
        pull_request=bool(issue.get("pull_request")),
    )


def _write_outputs(path: Path, result: ParsedComment) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    values = {
        "recognized": str(result.recognized).lower(),
        "command": result.command or "",
        "write_request": str(result.write_request).lower(),
        "authorized_write": str(result.authorized_write).lower(),
        "patch_executor": str(result.patch_executor).lower(),
        "source_format": result.source_format,
        "pull_request": str(result.pull_request).lower(),
        "issue_number": str(result.issue_number or ""),
    }
    with path.open("a", encoding="utf-8") as output:
        for name, value in values.items():
            output.write(f"{name}={value}\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--event-path",
        default=os.getenv("GITHUB_EVENT_PATH", ""),
        help="Path to the GitHub event JSON payload.",
    )
    parser.add_argument("--json-output", required=True)
    parser.add_argument("--objective-output", required=True)
    parser.add_argument(
        "--github-output",
        default=os.getenv("GITHUB_OUTPUT", ""),
        help="Optional runner-managed GitHub output file.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    event_path = Path(args.event_path)
    if not event_path.is_file():
        raise SystemExit("GitHub event payload is unavailable")

    payload = json.loads(event_path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise SystemExit("GitHub event payload must be a JSON object")
    result = parse_event(payload)

    json_path = Path(args.json_output)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(result.public_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    objective_path = Path(args.objective_output)
    objective_path.parent.mkdir(parents=True, exist_ok=True)
    objective_path.write_text(
        result.objective or "Repository engineering task",
        encoding="utf-8",
    )

    if args.github_output:
        _write_outputs(Path(args.github_output), result)

    print(
        json.dumps(
            {
                "recognized": result.recognized,
                "command": result.command,
                "authorized_write": result.authorized_write,
                "patch_executor": result.patch_executor,
                "source_format": result.source_format,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

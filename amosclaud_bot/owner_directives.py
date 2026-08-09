"""Normalize explicit trusted-owner comments into Amosclaud commands.

GitHub issue comments are not treated as commands merely because their author is
trusted. This module recognizes a small set of explicit directive formats and
converts them into the existing ``@amosclaud`` command contract. All execution,
approval, privacy, verification, publication, and branch rules remain enforced
by the existing dispatcher and bot runtime.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

TRUSTED_ASSOCIATIONS = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})
_MENTION_PREFIXES = ("@amosclaud", "@amosclaud-bot")
_DIRECTIVE_HEADING = re.compile(r"amosclaud(?:-bot)?\s+directives?", re.IGNORECASE)
_FIELD = re.compile(
    r"^\s*(?:[-*]\s*)?(?:\*\*)?([A-Za-z][A-Za-z ]{1,40})\s*:\s*(?:\*\*)?\s*(.*?)\s*$"
)


@dataclass(frozen=True)
class DirectiveNormalization:
    recognized: bool
    canonical_body: str = ""
    source_format: str = ""


def _compact(value: str) -> str:
    return " ".join((value or "").strip().split())


def _clean_field_value(value: str) -> str:
    text = _compact(value)
    while text.startswith("**") and text.endswith("**") and len(text) >= 4:
        text = text[2:-2].strip()
    return text


def _safe_constraint(value: str) -> str:
    """Preserve safety intent without falsely implying secret disclosure."""

    text = _clean_field_value(value)
    replacements = (
        (
            r"(?<![A-Za-z0-9_])`?\.env\.example`?(?![A-Za-z0-9_])",
            "the repository example environment template",
        ),
        (
            r"(?<![A-Za-z0-9_])`?\.env`?(?![A-Za-z0-9_])",
            "the repository environment template",
        ),
        (r"(?i)never\s+hard-?code\s+secrets?", "do not embed sensitive values"),
        (r"(?i)do\s+not\s+hard-?code\s+secrets?", "do not embed sensitive values"),
        (r"(?i)hard-?coded\s+secrets?", "embedded sensitive values"),
    )
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text)
    return _compact(text)


def _canonical_fix(parts: list[str]) -> DirectiveNormalization:
    objective = ". ".join(part.rstrip(". ") for part in parts if _compact(part))
    objective = _compact(objective).strip(". ")
    if not objective:
        return DirectiveNormalization(False)
    return DirectiveNormalization(
        True,
        canonical_body=f"@amosclaud fix {objective}",
        source_format="trusted-owner-directive",
    )


def _task_block(lines: list[str]) -> DirectiveNormalization:
    fields: dict[str, list[str]] = {}
    for line in lines:
        match = _FIELD.match(line)
        if not match:
            continue
        name = _compact(match.group(1)).lower()
        value = _clean_field_value(match.group(2))
        if value:
            fields.setdefault(name, []).append(value)

    tasks = fields.get("task", [])
    if not tasks:
        return DirectiveNormalization(False)

    parts = list(tasks)
    restrictions = fields.get("restriction", []) + fields.get("restrictions", [])
    if restrictions:
        parts.append("Constraint: " + "; ".join(_safe_constraint(item) for item in restrictions))
    outputs = fields.get("output", []) + fields.get("requested output", [])
    if outputs:
        parts.append("Requested output: " + "; ".join(_safe_constraint(item) for item in outputs))
    return _canonical_fix(parts)


def _directive_block(lines: list[str]) -> DirectiveNormalization:
    if not any(_DIRECTIVE_HEADING.search(line) for line in lines[:3]):
        return DirectiveNormalization(False)

    fields: dict[str, list[str]] = {}
    for line in lines[1:]:
        match = _FIELD.match(line)
        if not match:
            continue
        name = _compact(match.group(1)).lower()
        value = _clean_field_value(match.group(2))
        if value:
            fields.setdefault(name, []).append(value)

    objectives = fields.get("primary objective", []) + fields.get("objective", [])
    if not objectives:
        return DirectiveNormalization(False)

    parts = list(objectives)
    targets = fields.get("target directory", []) + fields.get("target", [])
    if targets:
        normalized_targets = [item.strip().strip("`").lstrip("/") for item in targets]
        parts.append("Target directory: " + ", ".join(normalized_targets))
    rules = fields.get("strict rule", []) + fields.get("rules", [])
    if rules:
        parts.append("Constraint: " + "; ".join(_safe_constraint(item) for item in rules))
    return _canonical_fix(parts)


def normalize_comment_body(body: str, author_association: str) -> DirectiveNormalization:
    """Return a canonical command for an explicit trusted-owner directive."""

    raw = (body or "").strip()
    lowered = raw.lower()
    if any(lowered.startswith(prefix) for prefix in _MENTION_PREFIXES):
        return DirectiveNormalization(False)
    if str(author_association or "NONE").upper() not in TRUSTED_ASSOCIATIONS:
        return DirectiveNormalization(False)

    if lowered.startswith("/amosclaud ") or lowered.startswith(".amosclaud "):
        remainder = _compact(raw[len("/amosclaud") :])
        return DirectiveNormalization(True, f"@amosclaud {remainder}", "trusted-owner-shorthand")

    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if not lines:
        return DirectiveNormalization(False)
    task = _task_block(lines)
    if task.recognized:
        return task
    return _directive_block(lines)


def normalize_owner_directive(payload: dict[str, Any]) -> DirectiveNormalization:
    """Normalize an issue-comment payload in place when its directive is trusted."""

    comment_value = payload.get("comment")
    if not isinstance(comment_value, Mapping):
        return DirectiveNormalization(False)
    comment = dict(comment_value)
    result = normalize_comment_body(
        str(comment.get("body") or ""),
        str(comment.get("author_association") or "NONE"),
    )
    if not result.recognized:
        return result

    comment["body"] = result.canonical_body
    payload["comment"] = comment
    payload["_amosclaud_owner_directive"] = {
        "recognized": True,
        "source_format": result.source_format,
        "comment_id": comment.get("id"),
    }
    return result

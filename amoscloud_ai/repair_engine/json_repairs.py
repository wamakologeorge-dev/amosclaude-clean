"""Deterministic JSON and JSON-with-comments repair support.

The repair is intentionally narrow: comments and trailing commas are removed
only when they occur outside quoted strings, then the result must parse as JSON.
Files that still fail parsing remain critical and are never rewritten.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Sequence

from .core import Finding, Repair, Severity, relative


def _strip_json_comments(text: str) -> str:
    output: list[str] = []
    index = 0
    in_string = False
    escaped = False

    while index < len(text):
        char = text[index]
        next_char = text[index + 1] if index + 1 < len(text) else ""

        if in_string:
            output.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue

        if char == '"':
            in_string = True
            output.append(char)
            index += 1
            continue

        if char == "/" and next_char == "/":
            index += 2
            while index < len(text) and text[index] not in "\r\n":
                index += 1
            continue

        if char == "/" and next_char == "*":
            index += 2
            while index + 1 < len(text) and text[index : index + 2] != "*/":
                if text[index] in "\r\n":
                    output.append(text[index])
                index += 1
            if index + 1 >= len(text):
                raise ValueError("unterminated JSON block comment")
            index += 2
            continue

        output.append(char)
        index += 1

    if in_string:
        raise ValueError("unterminated JSON string")
    return "".join(output)


def _strip_trailing_commas(text: str) -> str:
    output: list[str] = []
    index = 0
    in_string = False
    escaped = False

    while index < len(text):
        char = text[index]
        if in_string:
            output.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue

        if char == '"':
            in_string = True
            output.append(char)
            index += 1
            continue

        if char == ",":
            lookahead = index + 1
            while lookahead < len(text) and text[lookahead].isspace():
                lookahead += 1
            if lookahead < len(text) and text[lookahead] in "]}":
                index += 1
                continue

        output.append(char)
        index += 1

    return "".join(output)


def normalize_json_text(text: str) -> str:
    """Return canonical JSON when a safe JSONC normalization is possible."""
    cleaned = _strip_trailing_commas(_strip_json_comments(text))
    parsed = json.loads(cleaned)
    return json.dumps(parsed, indent=2, ensure_ascii=False, sort_keys=False) + "\n"


def safer_json_syntax(doctor: object, path: Path) -> list[Finding]:
    """Classify safely normalizable JSONC as repairable, not critical."""
    root = getattr(doctor, "root")
    rel = relative(path, root)
    text = path.read_text(encoding="utf-8")
    try:
        json.loads(text)
        return []
    except json.JSONDecodeError as original_error:
        try:
            normalize_json_text(text)
        except (json.JSONDecodeError, ValueError):
            return [
                Finding(
                    "json-syntax",
                    original_error.msg,
                    Severity.CRITICAL,
                    rel,
                    original_error.lineno,
                )
            ]
        return [
            Finding(
                "json-syntax",
                "JSON contains safely normalizable comments or trailing commas",
                Severity.REPAIRABLE,
                rel,
                original_error.lineno,
                "normalize JSON comments and trailing commas",
            )
        ]


def json_aware_fixer_apply(
    original_apply: Callable[[object, Sequence[Finding]], list[Repair]],
    fixer: object,
    findings: Sequence[Finding],
) -> list[Repair]:
    """Apply JSON normalization and delegate all other repairs to core Fixer."""
    json_paths = {
        finding.path
        for finding in findings
        if finding.code == "json-syntax"
        and finding.severity == Severity.REPAIRABLE
        and finding.path
    }
    delegated = [finding for finding in findings if finding.path not in json_paths]
    repairs = original_apply(fixer, delegated)
    root = getattr(fixer, "root")

    for rel in sorted(json_paths):
        path = root / rel
        if not path.is_file():
            continue
        original = path.read_text(encoding="utf-8")
        try:
            updated = normalize_json_text(original)
        except (json.JSONDecodeError, ValueError) as exc:
            repairs.append(Repair("normalize-json", rel, f"refused unsafe JSON repair: {exc}", False))
            continue
        changed = updated != original
        if changed:
            path.write_text(updated, encoding="utf-8")
        repairs.append(
            Repair(
                "normalize-json",
                rel,
                "remove JSON comments/trailing commas and emit validated canonical JSON",
                changed,
            )
        )

    return repairs

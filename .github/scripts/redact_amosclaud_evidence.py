#!/usr/bin/env python3
"""Redact and bound Amosclaud workflow evidence before artifact upload."""

from __future__ import annotations

import re
import sys
from pathlib import Path

MAX_FILE_CHARS = 200_000


def redact_text(text: str) -> str:
    text = re.sub(
        r"(?i)\b(api[_-]?key|token|secret|password)\s*[:=]\s*[^\s]+",
        lambda match: f"{match.group(1)}=[REDACTED]",
        text,
    )
    for pattern in (
        r"gh[pousr]_[A-Za-z0-9_]{20,}",
        r"amos_(?:svc|agent|auto)_[A-Za-z0-9_-]{16,}",
        r"sk-[A-Za-z0-9_-]{16,}",
        r"https?://[^\s/@:]+:[^\s/@]+@[^\s]+",
    ):
        text = re.sub(pattern, "[REDACTED]", text)

    if len(text) <= MAX_FILE_CHARS:
        return text
    half = MAX_FILE_CHARS // 2
    return text[:half] + "\n\n...[artifact evidence truncated]...\n\n" + text[-half:]


def redact_file(path: Path) -> None:
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8", errors="replace")
    path.write_text(redact_text(text), encoding="utf-8")


def main(arguments: list[str]) -> int:
    for argument in arguments:
        redact_file(Path(argument))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

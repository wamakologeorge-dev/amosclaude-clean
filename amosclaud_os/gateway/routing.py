"""Intent routing for professional engineering commands."""

import re

ENGINEERING_ACTION = re.compile(
    r"\b(build|create|implement|fix|repair|test|verify|deploy|release|publish|"
    r"repository|file|folder|branch|commit|issue|merge request|pull request|ci)\b",
    re.IGNORECASE,
)
READ_ONLY = re.compile(r"\b(explain only|show only|do not edit|don't edit|read only)\b", re.IGNORECASE)


def is_engineering_command(objective: str) -> bool:
    return bool(ENGINEERING_ACTION.search(objective or "")) and not bool(READ_ONLY.search(objective or ""))

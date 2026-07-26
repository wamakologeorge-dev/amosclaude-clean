#!/usr/bin/env python3
"""Amosclaud autonomous background engineering bot.

This wrapper performs repository preflight, records bounded failure evidence,
injects the Python engineering book into the repair context, and delegates patch
generation and verification to the signed, one-time Amosclaud Fixer boundary.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
BOOK = ROOT / "docs" / "PYTHON_AUTONOMOUS_ENGINEERING_BOOK.md"
SECURED_FIXER = ROOT / ".github" / "scripts" / "run_secured_amosclaud_fixer.py"
FAILURE_LOG = ROOT / "amosclaud-failure.log"
BOT_REPORT = ROOT / "amosclaud-background-engineer-report.json"
SECTION_LIMIT = 20_000


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def verify_prerequisites() -> None:
    missing = [
        str(path.relative_to(ROOT))
        for path in (BOOK, SECURED_FIXER)
        if not path.is_file()
    ]
    if missing:
        raise RuntimeError("Missing bot prerequisites: " + ", ".join(missing))
    if not os.getenv("AMOSCLAUD_API_KEY", "").strip():
        raise RuntimeError("AMOSCLAUD_API_KEY is required")
    if not os.getenv("AMOSCLAUD_FIXER_GRANT", "").strip():
        raise RuntimeError("AMOSCLAUD_FIXER_GRANT is required")
    if not os.getenv("AMOSCLAUD_COMMAND_BUS_SECRET", "").strip():
        raise RuntimeError("AMOSCLAUD_COMMAND_BUS_SECRET is required")


def _bounded(text: str, limit: int = SECTION_LIMIT) -> str:
    """Keep both the beginning and end of every evidence section."""
    if len(text) <= limit:
        return text
    half = limit // 2
    return text[:half] + "\n...[section truncated]...\n" + text[-half:]


def _previous_failure_evidence() -> str:
    """Preserve setup failures captured before the background engineer starts."""
    if not FAILURE_LOG.is_file():
        return ""
    content = FAILURE_LOG.read_text(encoding="utf-8", errors="replace").strip()
    if not content:
        return ""
    return "=== PREVIOUS WORKFLOW FAILURE EVIDENCE ===\n" + _bounded(content)


def collect_failure_evidence() -> tuple[bool, str]:
    commands = [
        [sys.executable, "-m", "compileall", "-q", "amoscloud_ai", "src", "tests"],
        [sys.executable, "-m", "pytest", "-q", "--disable-warnings", "--maxfail=25"],
    ]
    sections: list[str] = []
    previous = _previous_failure_evidence()
    if previous:
        sections.append(previous)

    passed = not previous
    for command in commands:
        try:
            result = run(command)
            output = result.stdout
            return_code = result.returncode
        except OSError as error:
            output = f"{type(error).__name__}: {error}"
            return_code = 1
        sections.append(f"$ {' '.join(command)}\n{_bounded(output)}")
        if return_code != 0:
            passed = False

    evidence = "\n\n".join(sections)
    instructions = BOOK.read_text(encoding="utf-8")
    repair_context = (
        "=== AMOSCLAUD PYTHON AUTONOMOUS ENGINEERING INSTRUCTIONS ===\n"
        + instructions
        + "\n\n=== CURRENT FAILURE EVIDENCE ===\n"
        + evidence
    )
    FAILURE_LOG.write_text(repair_context, encoding="utf-8")
    return passed, evidence


def main() -> int:
    verify_prerequisites()
    passed, evidence = collect_failure_evidence()
    if passed:
        BOT_REPORT.write_text(
            json.dumps(
                {
                    "status": "healthy",
                    "action": "none",
                    "message": "Compilation and pytest passed; no repair was generated.",
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        print("AMOSCLAUD_BACKGROUND_ENGINEER_STATUS=healthy")
        return 0

    env = os.environ.copy()
    env["AMOSCLAUD_FAILURE_LOG"] = FAILURE_LOG.name
    env["AMOSCLAUD_INSTRUCTION_BOOK"] = str(BOOK.relative_to(ROOT))
    env["AMOSCLAUD_SECURITY_ENFORCE"] = "true"
    result = subprocess.run(
        [sys.executable, str(SECURED_FIXER)],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    print(result.stdout)
    BOT_REPORT.write_text(
        json.dumps(
            {
                "status": (
                    "verified-repair" if result.returncode == 0 else "repair-failed"
                ),
                "fixer_return_code": result.returncode,
                "failure_excerpt": _bounded(evidence, 12_000),
                "fixer_output": _bounded(result.stdout, 12_000),
                "human_approval_required": False,
                "merge_policy": "auto-merge after required checks",
                "security": {
                    "signed_command_chain": True,
                    "grant_material_exposed": False,
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(
        "AMOSCLAUD_BACKGROUND_ENGINEER_STATUS="
        + ("verified-repair" if result.returncode == 0 else "repair-failed")
    )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())

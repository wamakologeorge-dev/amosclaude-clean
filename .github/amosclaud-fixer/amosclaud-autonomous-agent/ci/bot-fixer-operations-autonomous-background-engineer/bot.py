#!/usr/bin/env python3
"""Amosclaud autonomous background engineering bot.

This wrapper performs repository preflight, records failure evidence, injects the
Python engineering book into the repair context, and delegates patch generation
and verification to the guarded Amosclaud Fixer engine.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
BOOK = ROOT / "docs" / "PYTHON_AUTONOMOUS_ENGINEERING_BOOK.md"
FIXER = ROOT / ".github" / "scripts" / "amosclaud_fixer.py"
FAILURE_LOG = ROOT / "amosclaud-failure.log"
BOT_REPORT = ROOT / "amosclaud-background-engineer-report.json"


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def verify_prerequisites() -> None:
    missing = [str(path.relative_to(ROOT)) for path in (BOOK, FIXER) if not path.is_file()]
    if missing:
        raise RuntimeError("Missing bot prerequisites: " + ", ".join(missing))
    if not os.getenv("AMOSCLAUD_API_KEY", "").strip():
        raise RuntimeError("AMOSCLAUD_API_KEY is required")


def collect_failure_evidence() -> tuple[bool, str]:
    commands = [
        [sys.executable, "-m", "compileall", "-q", "amoscloud_ai", "src", "tests"],
        [sys.executable, "-m", "pytest", "-q", "--disable-warnings", "--maxfail=25"],
    ]
    sections: list[str] = []
    passed = True
    for command in commands:
        result = run(command)
        sections.append(f"$ {' '.join(command)}\n{result.stdout}")
        if result.returncode != 0:
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
    result = subprocess.run(
        [sys.executable, str(FIXER)],
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
                "status": "verified-repair" if result.returncode == 0 else "repair-failed",
                "fixer_return_code": result.returncode,
                "failure_excerpt": evidence[-12000:],
                "fixer_output": result.stdout[-12000:],
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

"""Amosclaud Repository Orchestrator and Self-Healing Engine.

This script backs the CI/CD pipeline and implements background 
self-correction mechanisms directly inside the repository main root.
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import subprocess
import sys
from typing import Optional

# Setup explicit logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] Amosclaud-System: %(message)s")
logger = logging.getLogger("AmosclaudOrchestrator")


class AmosclaudEngine:
    """Combines analytical monitoring (Amosclaud-ai) and autonomous self-fixing (Amosclaud-fixee)."""

    def __init__(self) -> None:
        self.agent_ai = "Amosclaud-ai"
        self.agent_fixer = "Amosclaud-fixee"

    def run_guardrails(self) -> bool:
        """[Amosclaud-ai] Analyzes repository code and catches syntax bugs."""
        logger.info(f"[{self.agent_ai}] Executing static analysis guardrails across root directory...")
        
        # Run strict flake8 validation looking for syntax crashes (E999, F821)
        result = subprocess.run(
            ["flake8", ".", "--count", "--select=E9,F63,F7,F82", "--show-source", "--statistics"],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            logger.info(f"[{self.agent_ai}] 🟢 Code passes verification tests. System clear.")
            return True
            
        logger.warning(f"[{self.agent_ai}] ❌ Syntax errors discovered in the current build context.")
        print(result.stdout)
        print(result.stderr)
        
        # Pass the failure log to the self-healing routine
        self.auto_heal(result.stdout)
        return False

    def auto_heal(self, log_output: str) -> None:
        """[Amosclaud-fixee] Parses the error report and rewrites files autonomously."""
        logger.info(f"[{self.agent_fixer}] 🔧 Activating autonomous recovery algorithms...")
        
        # Regex to target standard lint failure declarations: file_path:line:col: ErrorDetails
        error_pattern = re.compile(r"^\.(.+?\.py):(\d+):")
        
        fixed_any = False
        for line in log_output.splitlines():
            match = error_pattern.match(line)
            if match:
                file_path = "." + match.group(1)
                line_number = int(match.group(2))
                
                if os.path.exists(file_path):
                    logger.info(f"[{self.agent_fixer}] Targeting syntax discrepancy in file: {file_path} near line {line_number}")
                    if self.fix_syntax_anomaly(file_path, line_number, line):
                        fixed_any = True

        if fixed_any:
            logger.info(f"[{self.agent_fixer}] 🟢 Autonomous adjustments finalized. Re-testing repository health...")
            # Re-verify after adjustments
            final_check = subprocess.run(
                ["flake8", ".", "--count", "--select=E9,F63,F7,F82"],
                capture_output=True
            )
            if final_check.returncode == 0:
                logger.info(f"[{self.agent_fixer}] 🚀 Repair successfully validated. Staging patches for delivery...")
                self.commit_and_push_patch()
            else:
                logger.error(f"[{self.agent_fixer}] Additional structural obstacles encountered. Stopping loop.")
        else:
            logger.error(f"[{self.agent_fixer}] Unable to safely auto-remediate code patterns without structural maps.")

    def fix_syntax_anomaly(self, file_path: str, line_no: str | int, error_msg: str) -> bool:
        """Evaluates target source arrays and balances dangling brackets or unclosed parameters."""
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        idx = int(line_no) - 1
        target_line = lines[idx]

        # Scenario 1: Caught unclosed parenthesis cut-off at line boundary
        if "(" in target_line and ")" not in target_line and "def " in target_line:
            # Check if it was a FastAPI path parameter block cut off
            if "Depends" in target_line or "Request" in target_line or "path" in target_line:
                lines[idx] = target_line.rstrip() + "):\n"
                logger.info(f"[{self.agent_fixer}] Applied signature parameter closure constraint at index line {line_no}.")
            else:
                lines[idx] = target_line.rstrip() + ")\n"
                logger.info(f"[{self.agent_fixer}] Restored structural balancing parenthesis at index line {line_no}.")
                
        # Scenario 2: Caught missing variable definitions or module imports (F821)
        elif "BaseModel" in target_line and "from pydantic import BaseModel" not in "".join(lines):
            lines.insert(0, "from pydantic import BaseModel\n")
            logger.info(f"[{self.agent_fixer}] Injected structural missing dependency: 'from pydantic import BaseModel'.")
            
        elif "app.post" in target_line and "app = FastAPI" not in "".join(lines):
            lines.insert(0, "from fastapi import FastAPI\napp = FastAPI()\n")
            logger.info(f"[{self.agent_fixer}] Instantiated missing application reference object.")
        else:
            return False

        with open(file_path, "w", encoding="utf-8") as f:
            f.writelines(lines)
        return True

    def commit_and_push_patch(self) -> None:
        """Pushes the automated repair directly back to GitHub to keep the CI green."""
        try:
            subprocess.run(["git", "config", "global", "user.name", "Amosclaud-fixee"], check=True)
            subprocess.run(["git", "config", "global", "user.email", "fixer@amosclaud.internal"], check=True)
            subprocess.run(["git", "add", "-A"], check=True)
            subprocess.run(["git", "commit", "-m", "chore: autonomous patch applied via Amosclaud-fixee"], check=True)
            
            # Extract current branch dynamically
            branch_res = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True, check=True)
            current_branch = branch_res.stdout.strip()
            
            # Push changes upstream safely
            subprocess.run(["git", "push", "origin", current_branch], check=True)
            logger.info(f"[{self.agent_fixer}] 🎉 Autonomous code patch successfully committed and pushed to branch: {current_branch}")
        except subprocess.CalledProcessError as err:
            logger.error(f"[{self.agent_fixer}] Network conflict during git transport execution: {str(err)}")

    def serve(self) -> None:
        """Starts live service routing."""
        logger.info(f"[{self.agent_ai}] Spinning up runtime execution cluster...")
        import uvicorn
        uvicorn.run("main:app", host="0.0.0.0", port=8000)


def main() -> None:
    parser = argparse.ArgumentParser(description="Autonomous Self-Healing Script Orchestrator Core.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--test-guardrails", action="store_true")
    group.add_argument("--serve", action="store_true")

    args = parser.parse_args()
    engine = AmosclaudEngine()

    if args.test_guardrails:
        success = engine.run_guardrails()
        sys.exit(0 if success else 1)
    elif args.serve:
        engine.serve()


if __name__ == "__main__":
    main()

"""Amosclaud Internal Repository Reporting Bot.

Autonomous logging script engineered to process workflow execution results
and report telemetry profiles strictly back to native repository assets.
"""

from __future__ import annotations

import argparse
import datetime
import os
import subprocess
import sys


class AmosclaudReportBot:
    """Compiles workflow matrices and outputs markdown logs exclusively to the repository."""

    def __init__(self, run_status: str) -> None:
        self.agent_name = "Amosclaud-ai"
        self.run_status = run_status
        self.report_dir = "reports"

    def compile_repository_report(self) -> None:
        """Gathers system environment properties and generates a localized markdown report."""
        os.makedirs(self.report_dir, exist_ok=True)
        
        timestamp = datetime.datetime.utcnow().strftime("%Y-%m-%d_%H-%M-%S")
        report_filename = f"{self.report_dir}/execution_log_{timestamp}.md"
        
        # Gather Git structural metadata tokens safely
        try:
            commit_hash = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"]).decode().strip()
            branch_name = subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"]).decode().strip()
        except Exception:
            commit_hash = "unknown"
            branch_name = "unknown"

        # Construct the markdown data payload structure
        markdown_content = f"""# 🐦 Amosclaud Automation Status Report
*Generated autonomously via {self.agent_name}*

## 📋 Execution Summary
- **Timestamp**: {datetime.datetime.utcnow().isoformat()} UTC
- **Target Branch**: `{branch_name}`
- **Commit Signature**: `{commit_hash}`
- **Pipeline Evaluation**: { "🟢 SUCCESS" if self.run_status == "success" else "❌ FAILED" }

## ⚡ Monitoring State Parameters
- **Status Log**: 🐦 Amosclaud-ai is currently analyzing and working!
- **Operational Condition**: 🟢 Live & Active

---
*This configuration profile is logged exclusively within this architecture node.*
"""

        with open(report_filename, "w", encoding="utf-8") as f:
            f.write(markdown_content)
        
        print(f"[{self.agent_name}] Local workspace logging completed successfully: {report_filename}")
        self.save_and_synchronize_reports()

    def save_and_synchronize_reports(self) -> None:
        """Forces the automation runner to push the compiled reports straight into your repository tree."""
        try:
            subprocess.run(["git", "config", "global", "user.name", "Amosclaud-ai"], check=True)
            subprocess.run(["git", "config", "global", "user.email", "bot@amosclaud.internal"], check=True)
            subprocess.run(["git", "add", self.report_dir], check=True)
            
            # Use status verify checks to prevent throwing errors if no modifications exist
            status_check = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)
            if status_check.stdout.strip():
                subprocess.run(["git", "commit", "-m", f"chore: log execution telemetry report via {self.agent_name}"], check=True)
                
                # Dynamically isolate target active tracking branch to push directly back
                branch_out = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True, check=True)
                active_branch = branch_out.stdout.strip()
                
                subprocess.run(["git", "push", "origin", active_branch], check=True)
                print(f"[{self.agent_name}] Report matrix successfully synchronized upstream to your repository branch.")
            else:
                print(f"[{self.agent_name}] Local report definitions are already fully identical. Sync loop bypassed.")
        except subprocess.CalledProcessError as err:
            print(f"[{self.agent_name}] Warning: Version control transport intercept occurred: {str(err)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Amosclaud Local Repositories Report Bot driver.")
    parser.add_argument("--status", choices=["success", "failure"], required=True, help="Outcome pipeline evaluation metrics.")
    args = parser.parse_args()

    bot = AmosclaudReportBot(run_status=args.status)
    bot.compile_repository_report()


if __name__ == "__main__":
    main()

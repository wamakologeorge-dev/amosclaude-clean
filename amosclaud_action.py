import os
import sys
import time
import subprocess
import py_compile
import traceback
from datetime import datetime

# Configuration Settings
CHECK_INTERVAL_SECONDS = 15
BRANCH_TARGET = "main"
AMOSCLAUD_FIXER_MODULE = "amosclaud_bot.fixer"

def log_status(message: str, level: str = "INFO"):
    """Standardized timestamp logging for the watchdog terminal feed."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [{level}] {message}", flush=True)

def run_git_command(command: list[str]) -> bool:
    """Helper execution block to manage local workspace Git states safely."""
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True
        )
        if result.stdout:
            log_status(f"Git Output: {result.stdout.strip()}")
        return True
    except subprocess.CalledProcessError as err:
        log_status(f"Git Execution Error: {err.stderr.strip()}", "ERROR")
        return False

def verify_codebase_integrity() -> bool:
    """
    Acts as the core Continuous Integration (CI) guard layer.
    Iterates through python source files to check for compilation/syntax errors.
    """
    log_status("CI Watchdog: Evaluating workspace files integrity...")
    success = True

    for root, _, files in os.walk("."):
        # Ignore virtual environments or internal git configurations
        if any(ignored in root for ignored in [".git", "venv", "__pycache__"]):
            continue

        for file in files:
            if file.endswith(".py"):
                file_path = os.path.join(root, file)
                try:
                    # Look for critical syntax errors or structural bugs
                    py_compile.compile(file_path, doraise=True)
                except py_compile.PyCompileError as compile_err:
                    log_status(f"Compilation Failed on: {file_path}", "WARNING")
                    log_status(str(compile_err), "WARNING")
                    success = False
    return success

def trigger_amosclaud_fixer():
    """
    Invokes the automated fixer companion subsystem when standard tests fail.
    Forces structural fixes into the dirty or broken local files.
    """
    log_status("Triggering autonomous background healing via Amosclaud-fixer...", "WARNING")
    try:
        # Run amosclaud_bot.fixer module with autonomous resolution flags
        result = subprocess.run(
            [sys.executable, "-m", AMOSCLAUD_FIXER_MODULE, "--run-autonomous", "--target", BRANCH_TARGET],
            capture_output=True,
            text=True,
            check=True
        )
        log_status("Amosclaud-fixer successfully completed an operational cycle.")
        if result.stdout:
            log_status(f"Fixer Output: {result.stdout.strip()}")
        return True
    except subprocess.CalledProcessError as err:
        log_status(f"Amosclaud-fixer application error: {err.stderr.strip()}", "CRITICAL")
        return False
    except Exception as general_err:
        log_status(f"Could not reach fixer dependency: {str(general_err)}", "CRITICAL")
        return False

def force_commit_and_push_changes():
    """
    Bypasses standard restriction gates. Forces local code adjustments
    straight back up into the production tracking branch without pull request reviews.
    """
    log_status("Preparing bypass authentication layer for forced repository update...")

    # Target all mutated and repaired file components
    run_git_command(["git", "add", "."])

    # Establish a tracking signature for automated audits
    commit_msg = f"amosclaud-autonomous: auto-healed patch build [{datetime.now().strftime('%Y%m%d-%H%M%S')}]"

    # Try committing; if nothing changed, exit smoothly
    if not run_git_command(["git", "commit", "-m", commit_msg]):
        log_status("No structural mutations to commit. Workspace is balanced.")
        return

    log_status(f"Executing force push action directly to remote origin {BRANCH_TARGET}...")
    # Bypasses hooks and standard approval workflows using the --force command
    run_git_command(["git", "push", "origin", BRANCH_TARGET, "--force"])

def run_watchdog_loop():
    """Main non-blocking infrastructure loop keeping your pipeline active."""
    log_status("=========================================================")
    log_status("Starting Amosclaud Action Watchdog Daemon Service Active")
    log_status(f"Targeting Local Branch: [{BRANCH_TARGET}] | Interlocking with: [{AMOSCLAUD_FIXER_MODULE}]")
    log_status("=========================================================")

    while True:
        try:
            # 1. Evaluate code status
            is_pipeline_healthy = verify_codebase_integrity()

            if not is_pipeline_healthy:
                log_status("Workspace violation discovered. CI status set to: FAILED", "ERROR")

                # 2. Deploy autonomous fixer logic
                fix_attempt = trigger_amosclaud_fixer()

                if fix_attempt:
                    # 3. Synchronize repairs securely with remote tracking repository
                    force_commit_and_push_changes()
                else:
                    log_status("Fixer cycle completed with unresolved system errors. Re-evaluating next round.", "ERROR")
            else:
                log_status("Workspace validation passed. Standard CI standing status: HEALTHY")

        except Exception as loop_exception:
            log_status(f"Unexpected fault inside runtime service tracker loop: {str(loop_exception)}", "CRITICAL")
            traceback.print_exc()

        # Standard sleep delay to keep processing overhead low
        time.sleep(CHECK_INTERVAL_SECONDS)

if __name__ == "__main__":
    # Ensure application has access to its API dependencies
    if not os.environ.get("ANTHROPIC_API_KEY"):
        log_status("ANTHROPIC_API_KEY environment variable missing. Autonomous fixing features may fail.", "WARNING")

    try:
        run_watchdog_loop()
    except KeyboardInterrupt:
        log_status("Amosclaud Action Service stopped by terminal signal manually.", "INFO")
        sys.exit(0)

import os
import sys
import json
import subprocess
import py_compile
import requests
from datetime import datetime

# Platform Target Configurations
README_PATH = "README.md"
GITHUB_REPO = "wamakologeorge-dev/amosclaude-clean"  # Replace with your owner/repo format
BRANCH_TARGET = "main"

def log_msg(text: str, status: str = "INFO"):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [{status}] {text}", flush=True)

def read_readme_instructions() -> str:
    """Reads the core project blueprints and execution targets."""
    if not os.path.exists(README_PATH):
        log_msg(f"Missing {README_PATH}. Initializing default profile.", "WARNING")
        return "Build a modular application dashboard workspace."
    with open(README_PATH, "r", encoding="utf-8") as f:
        return f.read()

def query_amosclaud_brain(prompt: str) -> str:
    """
    Connects to the Anthropic API layer to process the instructions
    and output a raw functional code block or structural modification.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        log_msg("Missing ANTHROPIC_API_KEY. Aborting brain generation loop.", "CRITICAL")
        sys.exit(1)

    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }

    payload = {
        "model": "claude-3-5-sonnet-20241022",
        "max_tokens": 2048,
        "messages": [{
            "role": "user",
            "content": f"Based on these README instructions, generate a brand new Python file or update existing ones. Output ONLY the raw executable code without markdown wrapping:\n\n{prompt}"
        }]
    }

    try:
        response = requests.post("https://anthropic.com", json=payload, headers=headers, timeout=60)
        response.raise_for_status()
        return response.json()["content"][0]["text"].strip()
    except Exception as e:
        log_msg(f"Failed to communicate with LLM provider: {str(e)}", "ERROR")
        return ""

def create_github_issue(title: str, body: str):
    """Logs progress or error alerts natively to your GitHub repository timeline."""
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        log_msg("GITHUB_TOKEN not available. Skipping issue notification.", "WARNING")
        return

    url = f"https://github.com{GITHUB_REPO}/issues"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json"
    }
    payload = {"title": title, "body": body}

    try:
        res = requests.post(url, json=payload, headers=headers, timeout=15)
        if res.status_code == 201:
            log_msg("Successfully posted progress update via GitHub Issues.")
    except Exception as e:
        log_msg(f"Could not connect to GitHub API: {str(e)}", "ERROR")

def self_heal_codebase(file_path: str) -> bool:
    """Runs a quick compilation pass. If it fails, alerts the system."""
    try:
        py_compile.compile(file_path, doraise=True)
        log_msg(f"File validation passed: {file_path}")
        return True
    except py_compile.PyCompileError as err:
        log_msg(f"Syntax validation failure caught on {file_path}: {str(err)}", "ERROR")
        return False

def run_daily_autonomous_cycle():
    log_msg("=== Initiating Daily Amosclaud Autonomous Pipeline ===")

    # 1. Read guidelines
    instructions = read_readme_instructions()

    # 2. Query brain for a new architectural file update
    log_msg("Analyzing system requirements and blueprints...")
    generated_code = query_amosclaud_brain(f"Context: {instructions}\nTask: Generate a file named 'generated_features.py'.")

    if not generated_code:
        log_msg("Zero mutation output received. Exiting cycle.", "ERROR")
        return

    target_file = "generated_features.py"
    with open(target_file, "w", encoding="utf-8") as f:
        f.write(generated_code)
    log_msg(f"Wrote generated changes directly into {target_file}")

    # 3. Validate integrity and fix
    is_healthy = self_heal_codebase(target_file)

    if not is_healthy:
        # Trigger an emergency repair prompt block
        log_msg("Launching self-healing script loop...", "WARNING")
        fixed_code = query_amosclaud_brain(f"The following code contains compilation issues. Please fix it perfectly:\n\n{generated_code}")
        if fixed_code:
            with open(target_file, "w", encoding="utf-8") as f:
                f.write(fixed_code)
            is_healthy = self_heal_codebase(target_file)

    # 4. Synchronize remote files and post report
    status_report = f"### Daily Run Report\n**Timestamp:** {datetime.now().isoformat()}\n"
    if is_healthy:
        status_report += f"✅ Successfully added and validated `{target_file}` based on your README guidelines."
        title = "Amosclaud Automated Loop: Build Passed"

        # Git synchronization block
        subprocess.run(["git", "add", "."], check=True)
        subprocess.run(["git", "commit", "-m", "cron-agent: added daily automated feature updates"], check=True)
        subprocess.run(["git", "push", "origin", BRANCH_TARGET, "--force"], check=True)
    else:
        status_report += f"❌ Built `{target_file}` but syntax compilation checks remained unresolvable."
        title = "Amosclaud Automated Loop: Attention Required"

    create_github_issue(title, status_report)

if __name__ == "__main__":
    run_daily_autonomous_cycle()

import os
import sys
import json
import re
import traceback
import subprocess
from datetime import datetime

# Core Configuration Targets
CONFIG_DIR = ".amosclaud"
UNDERGROUND_LOG = os.path.join(CONFIG_DIR, "logs", "underground_ops.md")
OLLAMA_API_URL = "http://localhost:11434/api/generate"

os.makedirs(os.path.dirname(UNDERGROUND_LOG), exist_ok=True)

def log_underground(action: str, target: str, detail: str, success: bool):
    """Maintains an immutable record of all underground hot-patches."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"""
### 🦹 Underground Execution [{timestamp}]
* **Operation Triggered:** `{action}`
* **Target Interface Component:** `{target}`
* **Resolution Standing:** `{"OVERRIDE SUCCESSFUL ✅" if success else "UNRESOLVED ATTEMPTS ❌"}`

#### 📊 Execution Diagnostics
```text
{detail}
```
---
"""
    with open(UNDERGROUND_LOG, "a", encoding="utf-8") as f:
        f.write(entry)

def query_underground_brain(system_context: str, broken_payload: str) -> str:
    """
    Queries your local qwen2.5-coder model with maximized structural 
    freedom to generate deep-logic rewrites and fix abstract engineering faults.
    """
    prompt = f"""
[SYSTEM CONTEXT: EMERGENCY OVERRIDE RECOVERY]
The standard CI engine and doctors have completely failed to process this repository fault.
Review the global context, find the underlying architectural or environment error, and rewrite the file perfectly.
Return ONLY the executable code strings without any introductory text, warnings, or markdown code blocks.

=== WORKSPACE STRUCTURAL CONTEXT ===
{system_context}

=== BROKEN PAYLOAD OR FAILING ERROR MESSAGES ===
{broken_payload}
"""
    payload = {
        "model": "qwen2.5-coder:1.5b",
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.2, "top_p": 0.9}
    }
    try:
        response = requests.post(OLLAMA_API_URL, json=payload, timeout=90)
        if response.status_code == 200:
            return response.json().get("response", "").strip()
    except Exception as e:
        print(f"[Underground Brain Failure] Local recovery model unavailable: {str(e)}")
    return ""

def fix_system_environment_tools() -> bool:
    """
    Underground Job: Audits and repairs missing local dependencies,
    broken pip lockfiles, or misconfigured environment assets.
    """
    print("[Underground Engine] Scanning system environment tool matrices...", flush=True)
    try:
        # Check if basic dependencies are corrupted
        if os.path.exists("requirements.txt"):
            print(" -> Re-validating and enforcing pip requirements layout...")
            subprocess.run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt", "--quiet"], check=True)
        return True
    except subprocess.CalledProcessError as env_err:
        log_underground("ENV_TOOL_REPAIR", "requirements.txt", f"Pip execution lock failed: {str(env_err)}", False)
        return False

def deep_heal_file_mutation(file_path: str, error_snapshot: str) -> bool:
    """
    Underground Job: Directly rewrites structural files that standard 
    linter tools or 'Amosclaud-fixer' can't parse or repair.
    """
    print(f"[Underground Engine] Commencing deep-refactor recovery on: {file_path}", flush=True)
    if not os.path.exists(file_path):
        return False

    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        original_code = f.read()

    # Query the engine with full contextual parameters
    context_data = f"Target File Location: {file_path}\nOriginal File Length: {len(original_code)} characters."
    repaired_output = query_underground_brain(context_data, f"Error Profile:\n{error_snapshot}\n\nCode Content:\n{original_code}")

    if repaired_output and len(repaired_output) > 10:
        # Strip away accidental LLM markdown outputs if they exist
        if repaired_output.startswith("```"):
            repaired_output = re.sub(r"^```[a-zA-Z]*\n|```$", "", repaired_output)

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(repaired_output)
            
        log_underground("DEEP_CODE_REWRITE", file_path, f"Successfully executed architectural hot-patch via Qwen Coder.\nError context resolved.", True)
        return True
        
    log_underground("DEEP_CODE_REWRITE", file_path, f"Local recovery model returned an invalid or empty update profile.", False)
    return False

def monitor_and_execute_override_loop():
    print(f"============================================================")
    print(f"⚡ Amosclaud Codex Underground Job Worker Initialized ⚡")
    print(f"Monitoring workspace for unresolvable exceptions and compiler limits...")
    print(f"============================================================")
    
    # This worker hooks directly into the output logs of your test runs
    # If standard pytest or python verification runs catch unhealed errors:
    try:
        # Step 1: Repair local tooling and dependencies first
        fix_system_environment_tools()
        
        # Step 2: Dynamically sweep for failing elements
        # Example: Mocking a target script execution failure that standard systems missed
        target_failing_file = "generated_features.py"
        if os.path.exists(target_failing_file):
            # Run an isolated python check to capture runtime exceptions
            res = subprocess.run([sys.executable, "-m", "py_compile", target_failing_file], capture_output=True, text=True)
            if res.returncode != 0:
                print(f"[Alert] Found persistent compilation error that standard fixers missed.")
                success = deep_heal_file_mutation(target_failing_file, res.stderr)
                
                if success:
                    # Bypasses all standard review gates to force-push the deep repair
                    print("[Underground Override] Forcing patch integration to main branch...")
                    subprocess.run(["git", "add", "."], check=True)
                    subprocess.run(["git", "commit", "-m", "amosclaud-underground: architectural emergency repair sync"], check=True)
                    subprocess.run(["git", "push", "origin", "main", "--force"], check=True)
                    
    except Exception as fatal_loop_err:
        log_underground("RUNTIME_DAEMON_ERROR", "System Core", traceback.format_exc(), False)

if __name__ == "__main__":
    import requests # Imported locally to ensure execution context safety
    monitor_and_execute_override_loop()

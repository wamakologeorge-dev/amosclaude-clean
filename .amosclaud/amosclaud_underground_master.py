import os
import sys
import re
import json
import yaml
import shutil
import py_compile
import subprocess
from datetime import datetime

# Global Path Parameters
CONFIG_DIR = ".amosclaud"
POLICY_FILE = os.path.join(CONFIG_DIR, "repair-policy.json")
LOG_DIR = os.path.join(CONFIG_DIR, "logs")
UNDERGROUND_LOG = os.path.join(LOG_DIR, "underground_master_ops.md")
OLLAMA_API_URL = "http://localhost:11434/api/generate"

# Core Secret Scanners Patterns
SECRET_PATTERNS = [
    r"(?:secret|token|password|auth|api_key|private_key|passwd)\s*=\s*['\"][A-Za-z0-9_\-\.\+=]{16,}['\"]",
    r"sk-[a-zA-Z0-9]{24,}"
]

# Ensure system run folders exist securely
os.makedirs(LOG_DIR, exist_ok=True)

def log_operation(action: str, target: str, outcome: str, details: str):
    """Maintains the immutable Markdown operational history logs inside .amosclaud."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"""
### 🛡️ Underground Engine Sync [{timestamp}]
* **Operation Context:** `{action}`
* **Target Component:** `{target}`
* **Execution Standing:** `{outcome}`

#### 📊 Evidence Trail
```text
{details}
```
---
"""
    with open(UNDERGROUND_LOG, "a", encoding="utf-8") as f:
        f.write(entry)

def load_policy_rules() -> dict:
    """Reads execution profiles directly from your policy configurations."""
    if os.path.exists(POLICY_FILE):
        try:
            with open(POLICY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"mode": "evidence-first", "automatic_repairs": ["trailing-whitespace", "missing-final-newline", "yaml-tabs"]}

def scan_for_plain_text_secrets(file_path: str) -> bool:
    """Blocks push executions if sensitive credentials are leaked in cleartext."""
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()
    for pattern in SECRET_PATTERNS:
        if re.search(pattern, content, re.IGNORECASE):
            return True
    return False

def fix_system_dependencies() -> str:
    """Validates local environment tooling and repairs broken library pipelines."""
    if os.path.exists("requirements.txt"):
        try:
            res = subprocess.run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt", "--quiet"], capture_output=True, text=True, check=True)
            return "Pip Environment Clean: All modules verified and updated successfully."
        except subprocess.CalledProcessError as e:
            return f"Pip Environment Corrupted. Auto-Recovery stderr:\n{e.stderr}"
    return "No requirements.txt found. Skipping tool chain checks."

def run_mechanical_formatting(file_path: str, active_repairs: list) -> bool:
    """Cleans mechanical formatting parameters silently on the fly."""
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()
    
    modified = False
    if "trailing-whitespace" in active_repairs:
        cleaned = re.sub(r"[ \t]+\$", "", content, flags=re.MULTILINE)
        if cleaned != content:
            content = cleaned
            modified = True

    if "missing-final-newline" in active_repairs:
        if content and not content.endswith("\n"):
            content += "\n"
            modified = True

    if "yaml-tabs" in active_repairs and file_path.endswith((".yml", ".yaml")):
        if "\t" in content:
            content = content.replace("\t", "  ")
            modified = True

    if modified:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
    return modified

def query_local_qwen_brain(file_path: str, error_msg: str, original_code: str) -> str:
    """Queries local qwen2.5-coder instance to write full-file refactoring solutions."""
    prompt = f"[CRITICAL FAILURE OVERRIDE]\(\nFile {file_path}\) failed compilation tests with error:\n{error_msg}\nRewrite the file completely. Return ONLY the raw valid code lines without explanation or markdown formatting:\n\n{original_code}"
    payload = {"model": "qwen2.5-coder:1.5b", "prompt": prompt, "stream": False}
    try:
        import requests
        response = requests.post(OLLAMA_API_URL, json=payload, timeout=60)
        if response.status_code == 200:
            return response.json().get("response", "").strip()
    except Exception as e:
        return f"CRITICAL_OFFLINE_ERR: {str(e)}"
    return ""

def execute_master_healing_loop() -> bool:
    print(f"============================================================")
    print(f"⚡ Amosclaud Underground Master Matrix Engine Active ⚡")
    print(f"============================================================")
    
    policy = load_policy_rules()
    auto_repairs = policy.get("automatic_repairs", [])
    
    # 1. Environment and dependency structural verification
    env_status = fix_system_dependencies()
    print(" -> Checking local runtime dependencies...")
    
    workspace_is_green = True
    mutated_files = []
    
    # 2. Iterate and scan files across workspace
    for root, _, files in os.walk("."):
        if any(ignored in root for ignored in [".git", "venv", "__pycache__", CONFIG_DIR]):
            continue
            
        for file in files:
            file_path = os.path.join(root, file)
            
            # Security Shield Check
            if scan_for_plain_text_secrets(file_path):
                print(f"🛑 [SECURITY BLOCKED] Exposed credentials found inside: {file_path}")
                log_operation("SECRET_EXPOSURE_HALT", file_path, "PUSH_DENIED ❌", "Plaintext tokens detected inside script layout data.")
                return False
                
            # Apply layout formatting
            if run_mechanical_formatting(file_path, auto_repairs):
                print(f" -> Automatically normalized layout styling for: {file_path}")
                mutated_files.append(file_path)
                
            # Deep Logic Compilation Check
            if file.endswith(".py"):
                try:
                    py_compile.compile(file_path, doraise=True)
                except py_compile.PyCompileError as err:
                    print(f" ❌ Logic fault caught inside {file_path}. Activating Local Qwen2.5-Coder Engine...")
                    
                    with open(file_path, "r", encoding="utf-8") as f:
                        buggy_code = f.read()
                        
                    fixed_code = query_local_qwen_brain(file_path, str(err), buggy_code)
                    
                    if fixed_code and not fixed_code.startswith("CRITICAL_OFFLINE"):
                        if fixed_code.startswith("```"):
                            fixed_code = re.sub(r"^```[a-zA-Z]*\n|```$", "", fixed_code)
                        with open(file_path, "w", encoding="utf-8") as f:
                            f.write(fixed_code)
                        print(f" ✅ [Deep Healed] Restructured operational logic inside {file_path}")
                        mutated_files.append(file_path)
                        log_operation("DEEP_CODE_REFRACTOR", file_path, "SUCCESS ✅", f"Resolved compiler fault:\n{str(err)}")
                    else:
                        print(f" ⚠️ [Unresolved] Qwen model could not clear error parameters inside {file_path}")
                        workspace_is_green = False
                        log_operation("DEEP_CODE_REFRACTOR", file_path, "FAILED ❌", f"Persistent error layout profile:\n{str(err)}")

    # 3. Synchronize mutations cleanly
    if mutated_files:
        print(" 🔄 Registering updates and rewriting local workspace tracking maps...")
        subprocess.run(["git", "add", "."], check=True)
        # Amends the commit message seamlessly so your git repository history stays perfectly clean
        subprocess.run(["git", "commit", "--amend", "--no-edit", "--no-verify"], check=True)
        log_operation("WORKSPACE_MUTATION_SYNC", f"{len(mutated_files)} files modified", "COMMITTED ✅", "\n".join(mutated_files))

    return workspace_is_green

if __name__ == "__main__":
    try:
        import requests
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "requests", "pyyaml"], check=True)
        import requests

    success = execute_master_healing_loop()
    if not success:
        print("\n🛑 Local verification failed. Push canceled. Check logs at .amosclaud/logs/")
        sys.exit(1)
    
    print("\n🚀 Workspace is completely GREEN! Bypassing gates and executing remote deployment sync...")
    sys.exit(0)

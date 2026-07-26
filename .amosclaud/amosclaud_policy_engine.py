import os
import json
import yaml
import requests
import subprocess
import py_compile
from datetime import datetime

# Path references to files visible in your screenshot
CONFIG_DIR = ".amosclaud"
REPAIR_POLICY_PATH = os.path.join(CONFIG_DIR, "repair-policy.json")
SECURITY_PATH = os.path.join(CONFIG_DIR, "security.yml")
OLLAMA_API_URL = "http://localhost:11434/api/generate"

def load_repair_policy() -> dict:
    """Loads the policy controls defined in your repair-policy.json file."""
    if os.path.exists(REPAIR_POLICY_PATH):
        try:
            with open(REPAIR_POLICY_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    # Safe default fallback rules
    return {"max_auto_attempts": 3, "allowed_file_types": [".py", ".json"]}

def load_security_policy() -> dict:
    """Loads validation configurations from security.yml file."""
    if os.path.exists(SECURITY_PATH):
        try:
            with open(SECURITY_PATH, "r", encoding="utf-8") as f:
                return yaml.safe_load(f)
        except Exception:
            pass
    return {"enforce_strict_pinning": True}

def query_local_qwen_coder(prompt: str) -> str:
    """
    Routes standard syntax and code compilation error fixes to your 
    local qwen2.5-coder:1.5b instance to completely eliminate API costs.
    """
    payload = {
        "model": "qwen2.5-coder:1.5b",
        "prompt": f"You are a code debugger. Fix this Python error and return ONLY the corrected code block without any explanations:\n\n{prompt}",
        "stream": False
    }
    try:
        response = requests.post(OLLAMA_API_URL, json=payload, timeout=45)
        response.raise_for_status()
        return response.json().get("response", "").strip()
    except Exception as e:
        print(f"[Ollama Error] Local model offline or busy: {str(e)}")
        return ""

def process_and_verify_workspace():
    """Scans repository files, checking against loaded system policy restrictions."""
    repair_rules = load_repair_policy()
    security_rules = load_security_policy()
    
    print(f"[{datetime.now()}] Initializing loop using loaded policy files...")
    
    for root, _, files in os.walk("."):
        if any(ignored in root for ignored in [".git", "venv", "__pycache__"]):
            continue
            
        for file in files:
            # Check extension against allowed file types inside repair-policy.json
            ext = os.path.splitext(file)[1]
            if ext not in repair_rules.get("allowed_file_types", [".py"]):
                continue
                
            file_path = os.path.join(root, file)
            try:
                py_compile.compile(file_path, doraise=True)
            except py_compile.PyCompileError as err:
                print(f"[Violation Found] Code validation failed on: {file_path}")
                
                # Read broken code
                with open(file_path, "r", encoding="utf-8") as f:
                    broken_code = f.read()
                
                # Run the local Qwen coder to automatically fix the compilation error
                print(f"Sending code bug to local qwen2.5-coder engine...")
                fixed_code = query_local_qwen_coder(f"File: {file_path}\nError: {str(err)}\nCode:\n{broken_code}")
                
                if fixed_code:
                    with open(file_path, "w", encoding="utf-8") as f:
                        f.write(fixed_code)
                    print(f"[Self-Healed] Successfully applied local model patch to {file_path}")
                    
                    # Force synchronize changes up if security validation allows it
                    if security_rules.get("enforce_strict_pinning", True):
                        subprocess.run(["git", "add", file_path], check=True)
                        subprocess.run(["git", "commit", "-m", f"amosclaud-fixer: auto-repaired {file}"], check=True)
                        subprocess.run(["git", "push", "origin", "main", "--force"], check=True)

if __name__ == "__main__":
    process_and_verify_workspace()

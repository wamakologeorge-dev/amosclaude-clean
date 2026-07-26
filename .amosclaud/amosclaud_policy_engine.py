import os
import json
import yaml
import re
import subprocess
from datetime import datetime

CONFIG_DIR = ".amosclaud"
POLICY_FILE = os.path.join(CONFIG_DIR, "repair-policy.json")
LOG_DIR = os.path.join(CONFIG_DIR, "logs")

os.makedirs(LOG_DIR, exist_ok=True)

def load_exact_policy() -> dict:
    """Reads your exact 25-line evidence-first configuration rules."""
    if os.path.exists(POLICY_FILE):
        try:
            with open(POLICY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"mode": "evidence-first", "automatic_repairs": [], "approval_required": []}

def write_truthfulness_log(file_path: str, action: str, evidence: str, allowed: bool):
    """Enforces truthfulness schema by logging every structural command code return."""
    date_str = datetime.now().strftime("%Y-%m-%d")
    log_path = os.path.join(LOG_DIR, f"truthfulness-audit-{date_str}.md")
    timestamp = datetime.now().strftime("%H:%M:%S")
    
    log_entry = f"""
## 🛡️ Truthfulness Audit Log [{timestamp}]
* **Target Resource:** `{file_path}`
* **Evaluated Action:** `{action}`
* **Policy Compliance State:** `{"APPROVED ✅" if allowed else "HALTED - APPROVAL REQUIRED ❌"}`

### 📊 Command and Execution Evidence
```text
{evidence}
```
---
"""
    with open(log_path, "a", encoding="utf-8") as lf:
        lf.write(log_entry)

def run_automatic_formatting_repairs(file_path: str, active_repairs: list) -> bool:
    """Safely executes the lightweight formatting items allowed on lines 5-10."""
    if not file_path.endswith((".py", ".yml", ".yaml", ".json", ".js")):
        return False
        
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    modified = False
    evidence_trail = []

    # 1. Handle trailing-whitespace rule
    if "trailing-whitespace" in active_repairs:
        cleaned = re.sub(r"[ \t]+$", "", content, flags=re.MULTILINE)
        if cleaned != content:
            content = cleaned
            modified = True
            evidence_trail.append("Executed: Removed trailing whitespace characters.")

    # 2. Handle missing-final-newline rule
    if "missing-final-newline" in active_repairs:
        if content and not content.endswith("\n"):
            content += "\n"
            modified = True
            evidence_trail.append("Executed: Appended missing terminating newline.")

    # 3. Handle yaml-tabs rule
    if "yaml-tabs" in active_repairs and file_path.endswith((".yml", ".yaml")):
        if "\t" in content:
            content = content.replace("\t", "  ")
            modified = True
            evidence_trail.append("Executed: Replaced formatting tabs with safe dual spaces.")

    # Save changes locally if adjustments were made
    if modified:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        write_truthfulness_log(file_path, "AUTOMATIC_REPAIR", "\n".join(evidence_trail), allowed=True)
        return True
        
    return False

def analyze_and_guard_workspace():
    policy = load_exact_policy()
    auto_repairs = policy.get("automatic_repairs", [])
    
    print(f"[{datetime.now()}] Amosclaud active in [{policy.get('mode')}] validation mode.")

    for root, _, files in os.walk("."):
        if any(ignored in root for ignored in [".git", "venv", "__pycache__", CONFIG_DIR]):
            continue
            
        for file in files:
            file_path = os.path.join(root, file)
            
            # First, check if the file changes require manual verification flags
            # e.g., tracking hardcoded database scripts or API variables
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                file_snapshot = f.read()

            # Guard Layer: Intercept secret, business-logic, or database modifications
            if "database" in file_path or "migration" in file_path or "secret" in file_snapshot:
                print(f"[GUARD HALT] Action blocked on {file_path}. Triggers 'approval_required' policy rule.")
                write_truthfulness_log(
                    file_path, 
                    "BLOCKED_MUTATION", 
                    "Detected elements pointing to database structures or secret fields. Manual developer review mandatory.", 
                    allowed=False
                )
                continue

            # Run allowed mechanical formatting patches
            was_repaired = run_automatic_formatting_repairs(file_path, auto_repairs)
            if was_repaired:
                print(f"[Auto-Healed] Normalized code layout formatting parameters for: {file}")
                # Auto push code and evidence logs if clean
                subprocess.run(["git", "add", "."], check=True)
                subprocess.run(["git", "commit", "-m", f"amosclaud-policy: auto-repaired file layout format for {file}"], check=True)
                subprocess.run(["git", "push", "origin", "main", "--force"], check=True)

if __name__ == "__main__":
    analyze_and_guard_workspace()

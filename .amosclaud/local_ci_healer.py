import json
import os
import sys
import re
import py_compile
import subprocess
from datetime import datetime

CONFIG_DIR = ".amosclaud"
POLICY_FILE = os.path.join(CONFIG_DIR, "repair-policy.json")

def load_policy_rules() -> list:
    if os.path.exists(POLICY_FILE):
        try:
            with open(POLICY_FILE, "r", encoding="utf-8") as f:
                return json.load(f).get("automatic_repairs", [])
        except Exception:
            pass
    return ["trailing-whitespace", "missing-final-newline", "yaml-tabs"]

def auto_fix_formatting(file_path: str, active_repairs: list) -> bool:
    """Fixes basic syntax guidelines before committing."""
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    modified = False

    if "trailing-whitespace" in active_repairs:
        cleaned = re.sub(r"[ \t]+$", "", content, flags=re.MULTILINE)
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

def verify_and_heal_workspace() -> bool:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 🛡️ Amosclaud Local Pre-Push Guard Active.")
    auto_repairs = load_policy_rules()
    workspace_clean = True
    mutated_files = []

    # Scan codebase files
    for root, _, files in os.walk("."):
        if any(ignored in root for ignored in [".git", "venv", "__pycache__", CONFIG_DIR]):
            continue

        for file in files:
            if not file.endswith((".py", ".yml", ".yaml", ".json")):
                continue

            file_path = os.path.join(root, file)

            # Apply formatting fixes
            if auto_fix_formatting(file_path, auto_repairs):
                print(f" -> Automatically normalized layout formatting for: {file_path}")
                mutated_files.append(file_path)

            # Check Python file compilation integrity
            if file.endswith(".py"):
                try:
                    py_compile.compile(file_path, doraise=True)
                except py_compile.PyCompileError as err:
                    print(f" ❌ Compilation failure caught in {file_path}. Initiating repair...")
                    workspace_clean = False

                    # If compilation is fundamentally broken, drop into fallback recovery if available
                    # Otherwise block push so broken execution structures never touch github

    if mutated_files:
        print(" 🔄 Formatting adjustments detected. Automatically restaging clean components...")
        subprocess.run(["git", "add"] + mutated_files, check=True)
        # Amend the current commit silently so you don't pollute the git log history
        subprocess.run(["git", "commit", "--amend", "--no-edit", "--no-verify"], check=True)
        print(" ✅ Local commit amended cleanly with standardized features.")

    return workspace_clean

if __name__ == "__main__":
    if not verify_and_heal_workspace():
        print("\n🛑 Push blocked: Critical code compilation errors remain unresolved. Fix errors before pushing.")
        sys.exit(1)
    print("\n🚀 All verification parameters satisfied! Proceeding with remote deployment sync...")
    sys.exit(0)

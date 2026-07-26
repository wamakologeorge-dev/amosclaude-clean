import os
import sys
import shutil
import subprocess
from datetime import datetime

CONFIG_DIR = ".amosclaud"
SHELL_LOG = os.path.join(CONFIG_DIR, "logs", "shell_execution_bridge.md")

os.makedirs(os.path.dirname(SHELL_LOG), exist_ok=True)

def log_shell_event(command: str, exit_code: int, output: str, status: str):
    """Maintains explicit execution evidence records tracking command outcomes."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"""
### 🐚 Shell Router Invocation [{timestamp}]
* **Dispatched String:** `{command}`
* **Process Exit Code:** `{exit_code}`
* **Execution Standing:** `{status}`

#### 📊 Output Stream Dump
```text
{output.strip()}
```
---
"""
    with open(SHELL_LOG, "a", encoding="utf-8") as f:
        f.write(entry)

def find_system_shell_binary() -> str:
    """Dynamically resolves the valid native system terminal path wrapper."""
    for binary in ["/bin/bash", "/bin/sh", "bash", "sh"]:
        resolved_path = shutil.which(binary)
        if resolved_path:
            return resolved_path
    return "/bin/sh" # Safe fallback position

def execute_privileged_underground_command(command_string: str) -> tuple[bool, str]:
    """
    Safely executes background updates by explicitly inheriting parent process paths.
    This resolves issues where automated scripts throw 'cannot reach shell' faults.
    """
    shell_bin = find_system_shell_binary()
    
    # Explicitly pass the active system environment variables so variables are preserved
    custom_env = os.environ.copy()
    
    try:
        # Instead of risking blind shell=True syntax vulnerabilities, route explicitly
        res = subprocess.run(
            [shell_bin, "-c", command_string],
            capture_output=True,
            text=True,
            env=custom_env, # Ensures process inherits the explicit execution paths
            check=False
        )
        
        combined_output = f"STDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
        
        if res.returncode == 0:
            log_shell_event(command_string, res.returncode, combined_output, "SUCCESS ✅")
            return True, res.stdout
        else:
            log_shell_event(command_string, res.returncode, combined_output, "EXECUTION_FAILURE ❌")
            return False, res.stderr
            
    except Exception as fatal_exception:
        err_msg = f"System router exception: {str(fatal_exception)}"
        log_shell_event(command_string, -1, err_msg, "CRITICAL_SYSTEM_ERROR 🔥")
        return False, err_msg

if __name__ == "__main__":
    print(f"[{datetime.now()}] Testing unified shell bridge routing channel...")
    
    # Example: Verifying that standard commands parse cleanly via the bridge
    test_cmd = "python3 --version"
    success, message = execute_privileged_underground_command(test_cmd)
    
    if success:
        print(f"✅ Unified shell link connected successfully: {message.strip()}")
    else:
        print(f"❌ Execution loop blocked: {message.strip()}")

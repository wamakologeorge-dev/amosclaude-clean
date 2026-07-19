# ai/agent.py
import os
import re
import sys
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Tuple

# We support both Google Gemini and OpenAI. 
# We will attempt to import them and use whichever API key is configured.
try:
    import google.generativeai as genai
    HAS_GEMINI = True
except ImportError:
    HAS_GEMINI = False

try:
    import openai
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False

WORKSPACE_ROOT = Path(os.getcwd()).resolve()

# --- System Prompt for Codex Autonomy ---
CODEX_SYSTEM_PROMPT = """
You are the Amosclaud Codex Agent, an elite autonomous software engineer. 
You have direct read and write access to the local workspace and can execute terminal commands.

Your goal is to fulfill the user's request by writing clean, production-ready code, testing it, and self-correcting any errors.

You can perform actions by outputting special XML blocks in your response. You can output multiple actions in a single response. They will be executed in order.

AVAILABLE ACTIONS:

1. READ A FILE:
<read_file path="relative/path/to/file.py" />

2. WRITE OR OVERWRITE A FILE:
<write_file path="relative/path/to/file.py">
def my_new_code():
    print("Hello World")
</write_file>

3. SURGICALLY PATCH AN EXISTING FILE (Search and Replace):
Use this to make precise edits to existing files without rewriting the whole file.
<patch_file path="relative/path/to/file.py">
<search>
def old_code():
    print("old")
</search>
<replace>
def new_code():
    print("new")
</replace>
</patch_file>

4. EXECUTE A TERMINAL COMMAND:
Run tests, check syntax, or install packages.
<execute_command>
python -m py_compile relative/path/to/file.py
</execute_command>

RULES:
- Always check if files exist before writing or patching.
- After making edits, ALWAYS run a syntax check or tests using <execute_command> to verify your work.
- If your command execution returns an error, analyze the error and issue a correction in your next turn.
- Do not explain your steps excessively; let your code and actions do the work.
"""

class CodexAgent:
    def __init__(self):
        self.workspace_root = WORKSPACE_ROOT
        self._setup_llm()

    def _setup_llm(self):
        """Initializes the configured LLM client (Gemini or OpenAI)."""
        self.provider = None
        
        # Check for Gemini API Key
        gemini_key = os.getenv("GEMINI_API_KEY")
        if HAS_GEMINI and gemini_key:
            genai.configure(api_key=gemini_key)
            # Using Gemini 1.5 Pro/Flash for coding tasks
            self.model = genai.GenerativeModel(
                model_name="gemini-1.5-pro",
                system_instruction=CODEX_SYSTEM_PROMPT
            )
            self.provider = "gemini"
            print("[Codex Agent] Initialized with Google Gemini.")
            return

        # Check for OpenAI API Key
        openai_key = os.getenv("OPENAI_API_KEY")
        if HAS_OPENAI and openai_key:
            self.client = openai.OpenAI(api_key=openai_key)
            self.provider = "openai"
            print("[Codex Agent] Initialized with OpenAI GPT-4.")
            return

        print("[WARNING] No API keys found for Gemini or OpenAI. Running in Mock/Dry-Run mode.")
        self.provider = "mock"

    def get_workspace_map(self) -> str:
        """Generates a text-based directory tree of the workspace for the AI's context."""
        files_list = []
        ignored = {".git", "__pycache__", "node_modules", ".venv", "venv", ".pytest_cache"}
        for root, dirs, files in os.walk(self.workspace_root):
            dirs[:] = [d for d in dirs if d not in ignored and not d.startswith('.')]
            for f in files:
                if not f.startswith('.') and not f.endswith('.pyc'):
                    rel = Path(root).relative_to(self.workspace_root) / f
                    files_list.append(str(rel))
        return "\n".join(files_list)

    def execute_local_command(self, command: str) -> Tuple[int, str, str]:
        """Executes a shell command safely inside the workspace root."""
        print(f"[Executing Command] {command}")
        try:
            process = subprocess.run(
                command,
                shell=True,
                cwd=self.workspace_root,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=30
            )
            return process.returncode, process.stdout, process.stderr
        except subprocess.TimeoutExpired:
            return -1, "", "Command execution timed out after 30 seconds."
        except Exception as e:
            return -1, "", str(e)

    def parse_and_execute_actions(self, response_text: str) -> List[Dict[str, Any]]:
        """
        Parses XML action tags from the LLM response and executes them on the file system.
        """
        results = []

        # 1. Handle File Reads
        read_matches = re.findall(r'<read_file\s+path="([^"]+)"\s*/>', response_text)
        for path in read_matches:
            file_path = self.workspace_root / path
            if file_path.exists() and file_path.is_file():
                try:
                    content = file_path.read_text(encoding="utf-8")
                    results.append({"action": "read", "path": path, "success": True, "content": content})
                except Exception as e:
                    results.append({"action": "read", "path": path, "success": False, "error": str(e)})
            else:
                results.append({"action": "read", "path": path, "success": False, "error": "File not found."})

        # 2. Handle File Writes
        write_blocks = re.findall(r'<write_file\s+path="([^"]+)">([\s\S]*?)</write_file>', response_text)
        for path, content in write_blocks:
            file_path = self.workspace_root / path
            try:
                file_path.parent.mkdir(parents=True, exist_ok=True)
                file_path.write_text(content.strip(), encoding="utf-8")
                results.append({"action": "write", "path": path, "success": True})
                print(f"[Codex Written] {path}")
            except Exception as e:
                results.append({"action": "write", "path": path, "success": False, "error": str(e)})

        # 3. Handle File Patches (Search & Replace)
        patch_blocks = re.findall(r'<patch_file\s+path="([^"]+)">([\s\S]*?)</patch_file>', response_text)
        for path, patch_content in patch_blocks:
            file_path = self.workspace_root / path
            if not file_path.exists():
                results.append({"action": "patch", "path": path, "success": False, "error": "File not found to patch."})
                continue

            search_match = re.search(r'<search>([\s\S]*?)</search>', patch_content)
            replace_match = re.search(r'<replace>([\s\S]*?)</replace>', patch_content)

            if search_match and replace_match:
                search_str = search_match.group(1).strip()
                replace_str = replace_match.group(1).strip()
                
                try:
                    original_content = file_path.read_text(encoding="utf-8")
                    if search_str in original_content:
                        updated_content = original_content.replace(search_str, replace_str, 1)
                        file_path.write_text(updated_content, encoding="utf-8")
                        results.append({"action": "patch", "path": path, "success": True})
                        print(f"[Codex Patched] {path}")
                    else:
                        results.append({"action": "patch", "path": path, "success": False, "error": "Search block not found in file."})
                except Exception as e:
                    results.append({"action": "patch", "path": path, "success": False, "error": str(e)})
            else:
                results.append({"action": "patch", "path": path, "success": False, "error": "Invalid patch format. Missing <search> or <replace> tags."})

        # 4. Handle Command Executions
        cmd_blocks = re.findall(r'<execute_command>([\s\S]*?)</execute_command>', response_text)
        for cmd in cmd_blocks:
            cmd_clean = cmd.strip()
            code, stdout, stderr = self.execute_local_command(cmd_clean)
            results.append({
                "action": "execute",
                "command": cmd_clean,
                "exit_code": code,
                "stdout": stdout,
                "stderr": stderr,
                "success": (code == 0)
            })

        return results

    def run_turn(self, conversation_history: List[Dict[str, str]]) -> Tuple[str, List[Dict[str, Any]]]:
        """Sends the history to the LLM and processes any returned actions."""
        if self.provider == "mock":
            return "Error: No LLM provider configured. Set GEMINI_API_KEY or OPENAI_API_KEY.", []

        # Inject workspace map into the system prompt context
        workspace_map = self.get_workspace_map()
        context_prompt = f"\n\nCURRENT WORKSPACE FILES:\n{workspace_map}\n"
        
        # Build messages payload
        messages = []
        for msg in conversation_history:
            messages.append({"role": msg["role"], "content": msg["content"]})
            
        # Append workspace context to the last user message
        if messages:
            messages[-1]["content"] += context_prompt

        response_text = ""
        try:
            if self.provider == "gemini":
                # Convert messages to Gemini format
                chat = self.model.start_chat(history=[])
                response = chat.send_message(messages[-1]["content"])
                response_text = response.text
            elif self.provider == "openai":
                response = self.client.chat.completions.create(
                    model="gpt-4-turbo",
                    messages=[{"role": "system", "content": CODEX_SYSTEM_PROMPT}] + messages,
                    temperature=0.2
                )
                response_text = response.choices[0].message.content
        except Exception as e:
            return f"LLM API Error: {str(e)}", []

        # Execute actions parsed from LLM response
        execution_results = self.parse_and_execute_actions(response_text)
        return response_text, execution_results

    def run_autonomous_loop(self, user_prompt: str, max_iterations: int = 5):
        """
        The core Codex loop. It runs up to `max_iterations` times, executing actions,
        reading errors, and self-correcting until the task is complete.
        """
        print(f"\n[Codex Agent] Starting autonomous task: '{user_prompt}'")
        history = [{"role": "user", "content": user_prompt}]

        for iteration in range(1, max_iterations + 1):
            print(f"\n--- Codex Iteration {iteration}/{max_iterations} ---")
            response, results = self.run_turn(history)
            
            # Append AI response to history
            history.append({"role": "assistant", "content": response})
            
            if not results:
                print("[Codex Agent] Task complete. No further actions requested.")
                print(response)
                break

            # Format execution results as feedback for the next turn
            feedback = "EXECUTION RESULTS:\n"
            has_failures = False
            for res in results:
                if res["action"] in ["read", "write", "patch"]:
                    status = "SUCCESS" if res["success"] else f"FAILED: {res.get('error')}"
                    feedback += f"- Action: {res['action']} on '{res['path']}' -> {status}\n"
                    if res["action"] == "read" and res["success"]:
                        feedback += f"  Content:\n{res.get('content', '')}\n"
                else:
                    status = "SUCCESS" if res["success"] else "FAILED"
                    feedback += f"- Command: {res['command']} -> {status}\n"
                    if res.get("stdout"):
                        feedback += f"  stdout:\n{res['stdout']}\n"
                    if res.get("stderr"):
                        feedback += f"  stderr:\n{res['stderr']}\n"
                if not res["success"]:
                    has_failures = True

            history.append({"role": "user", "content": feedback})
            if not has_failures:
                print("[Codex Agent] Actions completed successfully.")

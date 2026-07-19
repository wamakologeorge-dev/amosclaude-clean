import os
import re
import json
import subprocess
from pathlib import Path
from typing import Dict, Any

class RealCodexAgent:
    def __init__(self, workspace_path: str, model_client):
        self.workspace = Path(workspace_path)
        self.model_client = model_client  # Your local backend model router instance
        self.max_loops = 5  # Allow up to 5 self-correction steps to solve bugs autonomously

    def run_task(self, objective: str) -> Dict[str, Any]:
        """
        Executes a true Codex Agent ReAct loop: Plan -> Act -> Check Environment -> Correct -> Report.
        """
        history = [
            {"role": "system", "content": self._get_system_guidelines()}
        ]
        
        current_prompt = f"Objective: {objective}\nBegin your execution reasoning loop."
        
        for loop_idx in range(self.max_loops):
            history.append({"role": "user", "content": current_prompt})
            
            # 1. Ask Qwen model for next step reasoning and file mutations
            ai_response = self.model_client.generate(history)
            history.append({"role": "assistant", "content": ai_response})
            
            print(f"--- [Codex Agent Loop {loop_idx + 1}] ---")
            print(ai_response)

            # 2. Parse out action requests from the model output
            write_action = self._parse_write_file(ai_response)
            exec_action = self._parse_execute_command(ai_response)

            # Scenario A: The model is done and provides a final analysis
            if not write_action and not exec_action:
                return {"status": "completed", "message": "Objective resolved successfully.", "output": ai_response}

            loop_feedback = ""

            # Scenario B: Agent demands writing/updating a script file
            if write_action:
                file_path = self.workspace / write_action["path"]
                os.makedirs(file_path.parent, exist_ok=True)
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(write_action["content"])
                loop_feedback += f"[SYSTEM FEEDBACK]: Successfully wrote file payload to {write_action['path']}.\n"

            # Scenario C: Agent requests evaluating file syntax or test commands
            if exec_action:
                command = exec_action["command"]
                # Enforce sandbox safety check guidelines
                if "rm -rf" in command or "sudo" in command:
                    loop_feedback += f"[SYSTEM ERROR]: Command '{command}' blocked by local security sandbox policies.\n"
                else:
                    result = subprocess.run(
                        command, shell=True, cwd=self.workspace, capture_output=True, text=True, timeout=30
                    )
                    if result.returncode == 0:
                        loop_feedback += f"[SYSTEM FEEDBACK]: Command executed with code 0.\nSTDOUT:\n{result.stdout}\n"
                    else:
                        # Feed the error directly back to the model's brain to initiate self-correction
                        loop_feedback += f"[SYSTEM RUNTIME ERROR]: Exit code {result.returncode}.\nSTDERR:\n{result.stderr}\n"

            # Prepare the environmental context for the next cycle
            current_prompt = f"Review the execution results and determine your next action:\n{loop_feedback}"

        return {"status": "failed", "message": "Max self-correction threshold reached without confirmation."}

    def _get_system_guidelines(self) -> str:
        return (
            "You are an advanced autonomous Codex Software Engineering Agent. You interact with the system via actions.\n"
            "To write or modify a code file, output your command using this exact markdown block:\n"
            "```write:path/to/file.py\n[CODE CONTENT HERE]\n```\n\n"
            "To compile, test, or execute code, output your action using this block:\n"
            "```execute\npython3 path/to/file.py\n```\n"
            "Always analyze execution feedback messages to resolve errors, fix code syntax, and handle failing builds dynamically."
        )

    def _parse_write_file(self, text: str) -> Dict[str, str]:
        match = re.search(r"```write:(.*?)\n(.*?)```", text, re.DOTALL)
        if match:
            return {"path": match.group(1).strip(), "content": match.group(2)}
        return None

    def _parse_execute_command(self, text: str) -> Dict[str, str]:
        match = re.search(r"```execute\n(.*?)```", text, re.DOTALL)
        if match:
            return {"command": match.group(1).strip()}
        return None

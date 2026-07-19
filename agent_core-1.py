"""
Amosclaud Autonomous Agent — core loop.

Implements a real Perceive -> Plan -> Act -> Verify -> Report cycle
against an OpenAI-compatible chat completions API. Every "Act" step
is a real tool call executed in a sandboxed workspace directory —
nothing is just described, everything that runs actually runs.

Usage:
    from agent_core import Agent, Workspace

    ws = Workspace("/path/to/repo")
    agent = Agent(
        base_url="https://your-provider.com/v1",
        api_key="...",
        model="your-model-name",
        workspace=ws,
    )
    result = agent.run("Add input validation to the /signup endpoint")
    print(result.summary)
"""

from __future__ import annotations

import json
import os
import subprocess
import textwrap
import dataclasses
from pathlib import Path
from typing import Any

from openai import OpenAI


# ---------------------------------------------------------------------------
# Sandboxed workspace: every file/command operation is confined to this root.
# ---------------------------------------------------------------------------

class WorkspaceError(Exception):
    pass


class Workspace:
    def __init__(self, root: str, allowed_commands: list[str] | None = None):
        self.root = Path(root).resolve()
        if not self.root.exists():
            raise WorkspaceError(f"Workspace root does not exist: {self.root}")
        # Allowlist of command prefixes the agent may run. Keep this tight —
        # this is the main safety boundary for the 'run_command' tool.
        self.allowed_commands = allowed_commands or [
            "pytest", "python -m pytest", "npm test", "npm run build",
            "npm install", "pip install", "ruff", "black --check",
            "git status", "git diff", "git add", "git commit",
        ]

    def _resolve(self, rel_path: str) -> Path:
        p = (self.root / rel_path).resolve()
        if self.root not in p.parents and p != self.root:
            raise WorkspaceError(f"Path escapes workspace: {rel_path}")
        return p

    def read_file(self, rel_path: str) -> str:
        p = self._resolve(rel_path)
        if not p.exists():
            raise WorkspaceError(f"File not found: {rel_path}")
        return p.read_text(errors="replace")

    def write_file(self, rel_path: str, content: str) -> str:
        p = self._resolve(rel_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return f"wrote {len(content)} bytes to {rel_path}"

    def list_tree(self, max_files: int = 200) -> list[str]:
        out = []
        for p in self.root.rglob("*"):
            if any(part.startswith(".") or part in ("node_modules", "__pycache__", "venv")
                   for part in p.relative_to(self.root).parts):
                continue
            if p.is_file():
                out.append(str(p.relative_to(self.root)))
            if len(out) >= max_files:
                break
        return out

    def run_command(self, cmd: str, timeout: int = 120) -> dict[str, Any]:
        if not any(cmd.strip().startswith(prefix) for prefix in self.allowed_commands):
            raise WorkspaceError(
                f"Command not in allowlist: {cmd!r}. "
                f"Allowed prefixes: {self.allowed_commands}"
            )
        proc = subprocess.run(
            cmd, shell=True, cwd=self.root, capture_output=True,
            text=True, timeout=timeout,
        )
        return {"cmd": cmd, "returncode": proc.returncode,
                "stdout": proc.stdout[-4000:], "stderr": proc.stderr[-4000:]}


# ---------------------------------------------------------------------------
# Tool schema exposed to the model. Plans must resolve to these calls only.
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file's contents from the workspace.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Create or overwrite a file in the workspace with new content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Run an allowlisted shell command in the workspace (tests, build, git).",
            "parameters": {
                "type": "object",
                "properties": {"cmd": {"type": "string"}},
                "required": ["cmd"],
            },
        },
    },
]

SYSTEM_PROMPT = textwrap.dedent("""\
    You are an autonomous coding agent operating on a real repository.
    You have three tools: read_file, write_file, run_command. Every call
    you make actually executes — there is no "preview mode".

    Process, strictly:
    1. Call read_file / inspect the file tree as needed to understand the
       code before changing anything. Do not guess at file contents.
    2. Make the minimum set of write_file calls needed to satisfy the
       objective.
    3. Always run a verification command (tests, build, or lint) after
       writing changes, via run_command.
    4. If verification fails, read the failure output, fix the files, and
       re-verify. Do not report success until a verification command has
       actually passed.
    5. When done, reply with plain text (no tool call) summarizing exactly
       what changed and what evidence (command + result) proves it works.
""")


# ---------------------------------------------------------------------------
# Agent loop
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class AgentResult:
    summary: str
    tool_calls_made: list[dict[str, Any]]
    verified: bool


class Agent:
    def __init__(self, base_url: str, api_key: str, model: str,
                 workspace: Workspace, max_steps: int = 20):
        self.client = OpenAI(base_url=base_url, api_key=api_key)
        self.model = model
        self.ws = workspace
        self.max_steps = max_steps

    def _dispatch(self, name: str, args: dict[str, Any]) -> str:
        try:
            if name == "read_file":
                return self.ws.read_file(args["path"])
            if name == "write_file":
                return self.ws.write_file(args["path"], args["content"])
            if name == "run_command":
                result = self.ws.run_command(args["cmd"])
                return json.dumps(result)
            return f"unknown tool: {name}"
        except WorkspaceError as e:
            return f"ERROR: {e}"

    def run(self, objective: str) -> AgentResult:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": (
                f"Objective: {objective}\n\n"
                f"Repo file tree (partial):\n" + "\n".join(self.ws.list_tree())
            )},
        ]

        tool_calls_made: list[dict[str, Any]] = []
        verified = False

        for step in range(self.max_steps):
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
            )
            msg = resp.choices[0].message

            if not msg.tool_calls:
                # Model produced a final natural-language report.
                return AgentResult(
                    summary=msg.content or "(no summary provided)",
                    tool_calls_made=tool_calls_made,
                    verified=verified,
                )

            messages.append({
                "role": "assistant",
                "content": msg.content,
                "tool_calls": [tc.model_dump() for tc in msg.tool_calls],
            })

            for tc in msg.tool_calls:
                name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {}
                result = self._dispatch(name, args)
                tool_calls_made.append({"tool": name, "args": args})

                if name == "run_command":
                    try:
                        parsed = json.loads(result)
                        if parsed.get("returncode") == 0:
                            verified = True
                    except (json.JSONDecodeError, TypeError):
                        pass

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result[:6000],
                })

        return AgentResult(
            summary="Stopped: max_steps reached before a final report.",
            tool_calls_made=tool_calls_made,
            verified=verified,
        )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run the autonomous agent on a repo.")
    parser.add_argument("--repo", required=True, help="Path to the repository")
    parser.add_argument("--objective", required=True, help="What the agent should do")
    parser.add_argument("--base-url", default=os.environ.get("AGENT_BASE_URL"))
    parser.add_argument("--api-key", default=os.environ.get("AGENT_API_KEY"))
    parser.add_argument("--model", default=os.environ.get("AGENT_MODEL"))
    args = parser.parse_args()

    ws = Workspace(args.repo)
    agent = Agent(base_url=args.base_url, api_key=args.api_key,
                   model=args.model, workspace=ws)
    result = agent.run(args.objective)

    print("\n=== SUMMARY ===")
    print(result.summary)
    print(f"\nVerified: {result.verified}")
    print(f"Tool calls made: {len(result.tool_calls_made)}")
    for tc in result.tool_calls_made:
        print(f"  - {tc['tool']}({tc['args']})")

"""Authenticated, branch-based repository work for Amosclaud.

This worker is deliberately separate from the public chat route: it only runs after
owner authentication, uses an isolated clone, and reports its result as a pull request.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


_REPOSITORY = "wamakologeorge-dev/amosclaude-clean"
_INSTRUCTION_FILES = ("AGENTS.md", "CLAUDE.md", "CONTRIBUTING.md", "README.md", ".github/copilot-instructions.md")
_BLOCKED_COMMANDS = ("curl ", "wget ", "nc ", "ssh ", "scp ", "sudo ", "rm -rf /", "printenv", "env |")


@dataclass
class WorkResult:
    status: str
    message: str
    logs: list[str] = field(default_factory=list)
    pull_request_url: Optional[str] = None


class PullRequestAgent:
    """Runs a bounded Claude coding loop and submits the verified result as a PR."""

    def __init__(self, task_id: str, objective: str, base_branch: str) -> None:
        self.task_id = task_id
        self.objective = objective
        self.base_branch = base_branch
        self.branch = f"amosclaud/agent-{task_id[:8]}"
        self.logs: list[str] = []
        self.root: Optional[Path] = None

    @staticmethod
    def configuration_error() -> Optional[str]:
        missing = [name for name in ("ANTHROPIC_API_KEY", "GITHUB_TOKEN") if not os.environ.get(name)]
        if missing:
            return "Repository execution is not configured: missing " + ", ".join(missing) + "."
        return None

    def _run(self, command: list[str], timeout: int = 180) -> str:
        if self.root is None:
            raise RuntimeError("workspace is not ready")
        rendered = " ".join(command)
        if any(token in rendered for token in _BLOCKED_COMMANDS):
            raise RuntimeError("command rejected by repository agent safety policy")
        completed = subprocess.run(
            command, cwd=self.root, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout, check=False
        )
        output = completed.stdout[-12000:]
        self.logs.append(f"$ {rendered}\n{output}".strip())
        if completed.returncode:
            raise RuntimeError(f"command failed ({completed.returncode}): {rendered}\n{output}")
        return output

    def _path(self, relative_path: str) -> Path:
        if self.root is None:
            raise RuntimeError("workspace is not ready")
        candidate = (self.root / relative_path).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise RuntimeError("path is outside the repository")
        return candidate

    def _instructions(self) -> str:
        sections: list[str] = []
        for filename in _INSTRUCTION_FILES:
            path = self._path(filename)
            if path.is_file():
                sections.append(f"--- {filename} ---\n{path.read_text(encoding='utf-8')[:16000]}")
        return "\n\n".join(sections) or "No repository instruction files exist."

    def _clone(self, tempdir: str) -> None:
        token = os.environ["GITHUB_TOKEN"]
        url = f"https://x-access-token:{token}@github.com/{_REPOSITORY}.git"
        subprocess.run(["git", "clone", "--depth", "1", "--branch", self.base_branch, url, tempdir], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.root = Path(tempdir)
        self._run(["git", "config", "user.name", "Amosclaud PR Agent"])
        self._run(["git", "config", "user.email", "amosclaud-agent@users.noreply.github.com"])
        self._run(["git", "checkout", "-b", self.branch])
        self.logs.append("Repository cloned and instruction files loaded before implementation.")

    def _apply_actions(self, response: str) -> bool:
        """Apply constrained XML actions. Returns whether any action was executed."""
        actions = False
        for path in re.findall(r'<read_file path="([^"]+)"\s*/>', response):
            file_path = self._path(path)
            content = file_path.read_text(encoding="utf-8") if file_path.is_file() else "FILE NOT FOUND"
            self.logs.append(f"Read {path}:\n{content[-8000:]}")
            actions = True
        for path, content in re.findall(r'<write_file path="([^"]+)">([\s\S]*?)</write_file>', response):
            file_path = self._path(path)
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content.strip() + "\n", encoding="utf-8")
            self.logs.append(f"Wrote {path}.")
            actions = True
        for path, patch in re.findall(r'<patch_file path="([^"]+)">([\s\S]*?)</patch_file>', response):
            search = re.search(r'<search>([\s\S]*?)</search>', patch)
            replace = re.search(r'<replace>([\s\S]*?)</replace>', patch)
            if not search or not replace:
                raise RuntimeError(f"invalid patch for {path}")
            file_path = self._path(path)
            original = file_path.read_text(encoding="utf-8")
            if search.group(1).strip() not in original:
                raise RuntimeError(f"patch search text was not found in {path}")
            file_path.write_text(original.replace(search.group(1).strip(), replace.group(1).strip(), 1), encoding="utf-8")
            self.logs.append(f"Patched {path}.")
            actions = True
        for command in re.findall(r'<execute_command>([\s\S]*?)</execute_command>', response):
            # Commands are tokenized; shell metacharacters are intentionally unavailable.
            self._run(command.strip().split(), timeout=300)
            actions = True
        return actions

    def _ask_claude(self, messages: list[dict[str, str]]) -> str:
        import anthropic

        prompt = f"""You are the Amosclaud PR Agent. Complete the owner request in this repository: {self.objective}

You must follow these instructions before editing:\n{self._instructions()}

Work autonomously. Inspect before changing; make a plan; write tests when appropriate; run the repository's required checks after each file change. Use only these XML tools: <read_file path=\"...\" />, <write_file path=\"...\">...</write_file>, <patch_file path=\"...\"><search>old</search><replace>new</replace></patch_file>, <execute_command>command arguments only</execute_command>. Do not use network commands, secrets, or shell operators. When work and validation are complete, return a concise final summary with no tool tags."""
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        response = client.messages.create(
            model=os.environ.get("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest"), max_tokens=4000, system=prompt, messages=messages
        )
        return "".join(block.text for block in response.content if getattr(block, "type", "") == "text")

    def _create_pull_request(self) -> str:
        token = os.environ["GITHUB_TOKEN"]
        payload = json.dumps({"title": f"Amosclaud: {self.objective[:80]}", "head": self.branch, "base": self.base_branch, "body": "Automated by Amosclaud PR Agent. The task log and validation results are available from Amosclaud."}).encode()
        request = urllib.request.Request(f"https://api.github.com/repos/{_REPOSITORY}/pulls", data=payload, headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode())["html_url"]

    def execute(self) -> WorkResult:
        error = self.configuration_error()
        if error:
            return WorkResult("failed", error, [error])
        tempdir = tempfile.mkdtemp(prefix="amosclaud-agent-")
        try:
            self._clone(tempdir)
            history = [{"role": "user", "content": self.objective}]
            final_reply = ""
            for _ in range(8):
                reply = self._ask_claude(history)
                history.append({"role": "assistant", "content": reply})
                if not self._apply_actions(reply):
                    final_reply = reply.strip()
                    break
                history.append({"role": "user", "content": "Continue from the action results in the repository. Inspect failures, fix them, and validate before completing."})
            changed = self._run(["git", "status", "--porcelain"])
            if not changed.strip():
                return WorkResult("completed", final_reply or "Analysis completed; no repository changes were needed.", self.logs)
            self._run(["git", "add", "--all"])
            self._run(["git", "commit", "-m", f"Amosclaud: {self.objective[:60]}"])
            self._run(["git", "push", "origin", self.branch], timeout=300)
            url = self._create_pull_request()
            return WorkResult("completed", final_reply or "Implementation complete and submitted for review.", self.logs, url)
        except Exception as exc:
            self.logs.append(f"Task failed: {exc}")
            return WorkResult("failed", "The PR agent stopped before opening a pull request. Review the task log and correct the reported blocker.", self.logs)
        finally:
            self.root = None
            shutil.rmtree(tempdir, ignore_errors=True)

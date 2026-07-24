"""Capabilities connected directly to the existing Autonomous kernel."""
from __future__ import annotations

from pathlib import Path
from typing import Any


class AutonomousConnectorHub:
    """Single capability hub; never a separate Autonomous implementation."""

    def __init__(self, workspace: Path | str) -> None:
        self.workspace = Path(workspace).resolve()

    def capabilities(self) -> list[str]:
        return [
            "model-response", "model-configuration", "documents", "read-write",
            "keyboard-command", "test-results", "server-connector", "command-mode",
            "learning-basics", "jobs-command-panel", "ci", "weighting",
            "clone", "fork", "remote",
        ]

    def read_document(self, relative_path: str) -> dict[str, Any]:
        target = self._safe_path(relative_path)
        if not target.exists() or not target.is_file():
            return {"ok": False, "path": relative_path, "error": "file_not_found"}
        return {"ok": True, "path": relative_path, "content": target.read_text(encoding="utf-8", errors="replace")}

    def write_document(self, relative_path: str, content: str, *, authorized: bool) -> dict[str, Any]:
        if not authorized:
            return {"ok": False, "path": relative_path, "error": "write_not_authorized"}
        target = self._safe_path(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return {"ok": True, "path": relative_path, "bytes": len(content.encode())}

    def test_result(self, name: str, passed: bool, evidence: str = "") -> dict[str, Any]:
        return {"name": name, "passed": passed, "status": "passed" if passed else "failed", "evidence": evidence}

    def jobs(self) -> list[dict[str, str]]:
        return [
            {"command": "create", "description": "Create or improve a project"},
            {"command": "fix", "description": "Diagnose, repair, and verify"},
            {"command": "deploy", "description": "Deploy through governed backend services"},
            {"command": "monitor", "description": "Inspect health, logs, and failures"},
            {"command": "clone", "description": "Clone a selected repository"},
            {"command": "fork", "description": "Fork through connected repository services"},
        ]

    def _safe_path(self, relative_path: str) -> Path:
        target = (self.workspace / relative_path).resolve()
        if target != self.workspace and self.workspace not in target.parents:
            raise ValueError("Path escapes the Autonomous workspace")
        return target

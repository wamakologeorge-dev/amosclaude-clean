"""Workspace-safe tools exposed to the main Autonomous ReAct loop."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from src.services.code_analyzer import CodeAnalyzer
from src.services.file_manager import SafeFileManager
from src.services.runtime_exec import RuntimeExecutor

from .observations import Observation
from .tool_registry import ToolDefinition, ToolRegistry


def build_react_registry(workspace: Path) -> ToolRegistry:
    """Build the tool registry used by the single main Autonomous."""
    analyzer = CodeAnalyzer(workspace)
    files = SafeFileManager(workspace)
    runtime = RuntimeExecutor(workspace)
    registry = ToolRegistry()

    def inspect_repository(_: dict[str, Any]) -> Observation:
        evidence = tuple(analyzer.inspect())
        return Observation(
            tool="inspect_repository",
            success=not any(item.startswith("Syntax error:") for item in evidence),
            summary="Repository inspection completed",
            evidence=evidence,
        )

    def read_file(arguments: dict[str, Any]) -> Observation:
        path = str(arguments.get("path", "")).strip()
        if not path:
            raise ValueError("path is required")
        content = files.read(path)
        return Observation(
            tool="read_file",
            success=True,
            summary=f"Read {path}",
            evidence=(path,),
            data={"path": path, "content": content},
        )

    def write_file(arguments: dict[str, Any]) -> Observation:
        path = str(arguments.get("path", "")).strip()
        if not path:
            raise ValueError("path is required")
        content = str(arguments.get("content", ""))
        files.write(path, content, authorized=True)
        return Observation(
            tool="write_file",
            success=True,
            summary=f"Wrote {path}",
            evidence=(path,),
            data={"path": path, "bytes": len(content.encode("utf-8"))},
        )

    def verify_runtime(_: dict[str, Any]) -> Observation:
        checks = runtime.verify()
        failures = [check for check in checks if not bool(check.get("passed"))]
        evidence = tuple(
            f"{check.get('command')}: {check.get('summary')}"
            for check in checks
        )
        return Observation(
            tool="verify_runtime",
            success=not failures,
            summary=(
                "Runtime verification passed"
                if not failures
                else f"{len(failures)} runtime check(s) failed"
            ),
            evidence=evidence,
            data={"checks": checks},
        )

    registry.register(
        ToolDefinition(
            name="inspect_repository",
            handler=inspect_repository,
            description="Inspect Python files and AST syntax evidence.",
        )
    )
    registry.register(
        ToolDefinition(
            name="read_file",
            handler=read_file,
            description="Read a UTF-8 file inside the controlled workspace.",
        )
    )
    registry.register(
        ToolDefinition(
            name="write_file",
            handler=write_file,
            description="Write a UTF-8 file inside the controlled workspace.",
            writes=True,
        )
    )
    registry.register(
        ToolDefinition(
            name="verify_runtime",
            handler=verify_runtime,
            description="Compile source and run repository tests.",
        )
    )
    return registry

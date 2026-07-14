from __future__ import annotations

import json
import shlex
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from amoscloud_ai.core.workspace import WorkspaceEngine, WorkspaceError


class AmoSyntaxError(ValueError):
    pass


ALLOWED_CAPABILITIES = {
    "workspace.read",
    "workspace.write",
    "workspace.list",
    "memory.read",
    "memory.write",
    "agent.respond",
}


@dataclass(frozen=True)
class AmoInstruction:
    opcode: str
    arguments: tuple[str, ...]
    line: int
    allowed_capabilities: frozenset[str] = frozenset()


@dataclass
class AmoProgram:
    name: str = "Unnamed Agent"
    goal: str = ""
    capabilities: set[str] = field(default_factory=set)
    memory: dict[str, str] = field(default_factory=dict)
    instructions: list[AmoInstruction] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "goal": self.goal,
            "capabilities": sorted(self.capabilities),
            "memory": dict(self.memory),
            "instructions": [
                {"opcode": item.opcode, "arguments": list(item.arguments), "line": item.line}
                for item in self.instructions
            ],
        }


def parse_amo(source: str) -> AmoProgram:
    program = AmoProgram()
    saw_header = False
    saw_statement = False

    for line_number, raw in enumerate(source.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue

        try:
            tokens = shlex.split(stripped, comments=False, posix=True)
        except ValueError as exc:
            raise AmoSyntaxError(f"Line {line_number}: {exc}") from exc
        if not tokens:
            continue

        keyword, *args = tokens
        if not saw_statement:
            saw_statement = True
            if keyword != "amo" or args != ["1"]:
                raise AmoSyntaxError("Amo program must begin with 'amo 1'")

        if keyword == "amo":
            if args != ["1"]:
                raise AmoSyntaxError(f"Line {line_number}: expected 'amo 1'")
            if saw_header:
                raise AmoSyntaxError(f"Line {line_number}: duplicate 'amo 1' header")
            saw_header = True
        elif keyword == "agent":
            _require_count(args, 1, line_number, "agent <name>")
            program.name = args[0]
        elif keyword == "goal":
            _require_count(args, 1, line_number, "goal <description>")
            program.goal = args[0]
        elif keyword == "allow":
            _require_count(args, 1, line_number, "allow <capability>")
            capability = args[0]
            if capability not in ALLOWED_CAPABILITIES:
                raise AmoSyntaxError(f"Line {line_number}: unsupported capability '{capability}'")
            program.capabilities.add(capability)
        elif keyword == "remember":
            if len(args) != 2:
                raise AmoSyntaxError(f"Line {line_number}: expected remember <key> <value>")
            program.memory[args[0]] = args[1]
        elif keyword in {"say", "list", "read", "write", "recall"}:
            program.instructions.append(
                AmoInstruction(keyword, tuple(args), line_number, frozenset(program.capabilities))
            )
        else:
            raise AmoSyntaxError(f"Line {line_number}: unknown instruction '{keyword}'")

    if not saw_header:
        raise AmoSyntaxError("Amo program must begin with 'amo 1'")
    return program


def _require_count(args: list[str], expected: int, line: int, usage: str) -> None:
    if len(args) != expected:
        raise AmoSyntaxError(f"Line {line}: expected {usage}")


class AmoRuntime:
    """Execute a constrained Amo program inside one Amosclaud workspace.

    Amo programs declare capabilities before they can perform an action. The
    runtime never invokes a shell and never permits paths outside the workspace.
    """

    def __init__(self, workspace: WorkspaceEngine | None = None):
        self.workspace = workspace or WorkspaceEngine()

    def execute(self, program: AmoProgram, *, input_text: str = "") -> dict[str, Any]:
        memory = dict(program.memory)
        memory["input"] = input_text
        output: list[str] = []
        trace: list[dict[str, Any]] = []

        try:
            for instruction in program.instructions:
                started = datetime.now(timezone.utc).isoformat()
                try:
                    result = self._execute_instruction(program, instruction, memory, output)
                except Exception as exc:
                    trace.append(
                        {
                            "line": instruction.line,
                            "opcode": instruction.opcode,
                            "status": "failed",
                            "started_at": started,
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                    )
                    raise
                trace.append(
                    {
                        "line": instruction.line,
                        "opcode": instruction.opcode,
                        "status": "completed",
                        "started_at": started,
                        "result": result,
                    }
                )
        except Exception:
            self.workspace.append_activity(
                {
                    "action": "amo.executed",
                    "agent": program.name,
                    "goal": program.goal,
                    "instructions": len(program.instructions),
                    "status": "failed",
                    "trace": trace,
                }
            )
            raise

        event = {
            "action": "amo.executed",
            "agent": program.name,
            "goal": program.goal,
            "instructions": len(program.instructions),
            "status": "completed",
            "trace": trace,
        }
        self.workspace.append_activity(event)
        return {
            "agent": program.name,
            "goal": program.goal,
            "output": output,
            "memory": memory,
            "trace": trace,
        }

    def _execute_instruction(
        self,
        program: AmoProgram,
        instruction: AmoInstruction,
        memory: dict[str, str],
        output: list[str],
    ) -> Any:
        op = instruction.opcode
        args = instruction.arguments

        if op == "say":
            self._require(program, "agent.respond", instruction.line)
            if len(args) != 1:
                raise AmoSyntaxError(f"Line {instruction.line}: expected say <text>")
            rendered = self._render(args[0], memory)
            output.append(rendered)
            return rendered

        if op == "recall":
            self._require(program, "memory.read", instruction.line)
            if len(args) != 1:
                raise AmoSyntaxError(f"Line {instruction.line}: expected recall <key>")
            value = memory.get(args[0], "")
            output.append(value)
            return value

        if op == "list":
            self._require(program, "workspace.list", instruction.line)
            if len(args) != 1:
                raise AmoSyntaxError(f"Line {instruction.line}: expected list <section>")
            items = self.workspace.list_items(args[0])
            output.append(json.dumps(items, ensure_ascii=False))
            return items

        if op == "read":
            self._require(program, "workspace.read", instruction.line)
            if len(args) != 2:
                raise AmoSyntaxError(f"Line {instruction.line}: expected read <path> <memory-key>")
            item = self.workspace.read_text(args[0])
            memory[args[1]] = item["content"]
            return {"path": item["path"], "stored_as": args[1]}

        if op == "write":
            self._require(program, "workspace.write", instruction.line)
            if len(args) != 2:
                raise AmoSyntaxError(f"Line {instruction.line}: expected write <path> <content>")
            path = self.workspace._safe_path(args[0])
            content = self._render(args[1], memory)
            self.workspace._atomic_write_text(path, content)
            return {"path": path.relative_to(self.workspace.root).as_posix(), "bytes": len(content.encode("utf-8"))}

        raise AmoSyntaxError(f"Line {instruction.line}: unsupported opcode '{op}'")

    @staticmethod
    def _render(template: str, memory: dict[str, str]) -> str:
        rendered = template
        for key, value in memory.items():
            rendered = rendered.replace("{{" + key + "}}", value)
        return rendered

    @staticmethod
    def _require(program: AmoProgram, capability: str, line: int) -> None:
        instruction = next((item for item in program.instructions if item.line == line), None)
        capabilities = instruction.allowed_capabilities if instruction is not None else frozenset()
        if capability not in capabilities:
            raise PermissionError(f"Line {line}: capability '{capability}' was not declared")

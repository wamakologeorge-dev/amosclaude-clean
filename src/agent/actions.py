"""Single Autonomous orchestrator for all Amosclaud entry points."""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from .engineering_loop import AutonomousEngineeringLoop, LoopOutcome
from .model import AutonomousModelGateway
from src.services.code_analyzer import CodeAnalyzer
from src.services.file_manager import SafeFileManager
from src.services.runtime_exec import RuntimeExecutor

@dataclass
class AutonomousTask:
    objective: str
    mode: str = "plan"
    authorized_writes: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

class AutonomousOrchestrator:
    """One shared coordinator for UI, API, webhooks, jobs, and agents."""
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()
        self.model = AutonomousModelGateway()
        self.analyzer = CodeAnalyzer(self.workspace)
        self.files = SafeFileManager(self.workspace)
        self.runtime = RuntimeExecutor(self.workspace)
        self.engineering_loop = AutonomousEngineeringLoop(
            analyzer=self.analyzer,
            model=self.model,
            files=self.files,
            runtime=self.runtime,
            max_attempts=2,
        )

    def run(self, task: AutonomousTask) -> LoopOutcome:
        return self.engineering_loop.run(
            objective=task.objective,
            mode=task.mode,
            authorized_writes=task.authorized_writes,
        )

def run_autonomous(objective: str, mode: str = "plan", authorized_writes: bool = False, workspace: str = ".") -> dict[str, Any]:
    task = AutonomousTask(objective=objective, mode=mode, authorized_writes=authorized_writes)
    return AutonomousOrchestrator(Path(workspace)).run(task).to_dict()

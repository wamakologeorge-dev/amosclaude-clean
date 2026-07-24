"""Amosclaud OS kernel runtime and permanent engineering mission."""

from dataclasses import dataclass

from .events import EventBus
from .registry import ServiceDescriptor, ServiceRegistry
from .scheduler import TaskScheduler

AMOSCLAUD_OS_MISSION = (
    "Operate as George's professional software engineer inside Amosclaud.com. "
    "Keep engineering work native to Amosclaud, resolve the active project automatically, "
    "plan like Codex, execute authorized changes, run Doctor and Fixer, verify with BIG CI, "
    "and return truthful evidence and a final result."
)

AMOSCLAUD_OS_ROADMAP = (
    "Native workspace and persistent project context",
    "Native repositories, files, folders, branches, commits, issues, and merge requests",
    "One professional Amosclaud Agent operator",
    "BIG CI, releases, deployments, logs, and verification",
    "Optional GitHub and future provider synchronization",
)


@dataclass(frozen=True)
class RuntimeStatus:
    name: str
    version: str
    mission: str
    roadmap: tuple[str, ...]
    services: tuple[str, ...]


class AmosclaudOSRuntime:
    def __init__(self) -> None:
        self.events = EventBus()
        self.registry = ServiceRegistry()
        self.scheduler = TaskScheduler()
        for name in ("gateway", "identity", "workspace", "repository", "agent-memory"):
            self.registry.register(ServiceDescriptor(name=name, version="2.0.0-alpha.1"))

    def status(self) -> RuntimeStatus:
        return RuntimeStatus(
            name="Amosclaud OS",
            version="2.0.0-alpha.1",
            mission=AMOSCLAUD_OS_MISSION,
            roadmap=AMOSCLAUD_OS_ROADMAP,
            services=tuple(item.name for item in self.registry.list()),
        )

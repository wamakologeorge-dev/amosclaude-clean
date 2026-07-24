"""Governed AmoModel service graph without arbitrary command execution."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ServiceNode:
    name: str
    dependencies: tuple[str, ...] = ()


DEFAULT_GRAPH = (
    ServiceNode("state-store"),
    ServiceNode("shared-database", ("state-store",)),
    ServiceNode("platform-byte-bus", ("shared-database",)),
    ServiceNode("repository-service", ("shared-database",)),
    ServiceNode("autonomous-worker", ("platform-byte-bus", "repository-service")),
    ServiceNode("fixer-worker", ("autonomous-worker",)),
    ServiceNode("ci-verification", ("repository-service",)),
    ServiceNode("pull-request-service", ("repository-service", "ci-verification")),
    ServiceNode("deployment-service", ("ci-verification",)),
    ServiceNode("amosclaud-api", ("shared-database", "platform-byte-bus")),
)


class ServiceGraph:
    """Deterministic lifecycle model for approved platform components."""

    def __init__(self, nodes: tuple[ServiceNode, ...] = DEFAULT_GRAPH) -> None:
        self.nodes = nodes

    def startup(self) -> dict[str, str]:
        states: dict[str, str] = {}
        for node in self.nodes:
            missing = [item for item in node.dependencies if states.get(item) != "ready"]
            states[node.name] = "blocked" if missing else "ready"
        return states

    def shutdown(self) -> dict[str, str]:
        return {node.name: "off" for node in reversed(self.nodes)}

    def healthy(self, services: dict[str, str]) -> bool:
        return all(services.get(node.name) == "ready" for node in self.nodes)

    def evidence(self, services: dict[str, str]) -> list[dict[str, object]]:
        evidence: list[dict[str, object]] = []
        for node in self.nodes:
            status = services.get(node.name, "unknown")
            evidence.append(
                {
                    "service": node.name,
                    "status": status,
                    "dependencies": list(node.dependencies),
                    "healthy": status == "ready",
                }
            )
        return evidence

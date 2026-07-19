"""Six intelligent foundation systems for the single Amosclaud Autonomous Core."""
from __future__ import annotations

import ast
import hashlib
import json
import sqlite3
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .curriculum import UniversalCurriculum


@dataclass
class FoundationContext:
    objective: str
    confidence: float
    risk: str
    related_files: list[str]
    memories: list[str]
    skills: list[str]
    allowed_actions: list[str]
    blocked_actions: list[str]
    missing_evidence: list[str]
    next_lesson: dict[str, Any]
    simulation: dict[str, Any] | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class KnowledgeGraph:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()
        self.index: dict[str, set[str]] = {}

    def build(self, limit: int = 500) -> None:
        self.index.clear()
        for path in sorted(self.workspace.rglob("*.py"))[:limit]:
            if any(part in {".git", ".venv", "venv", "node_modules", "__pycache__"} for part in path.parts):
                continue
            relative = path.relative_to(self.workspace).as_posix()
            terms = set(relative.lower().replace("/", " ").replace("_", " ").split())
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        terms.add(node.name.lower())
                    elif isinstance(node, ast.Import):
                        terms.update(alias.name.lower() for alias in node.names)
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        terms.add(node.module.lower())
            except (OSError, SyntaxError):
                pass
            self.index[relative] = terms

    def related(self, objective: str, limit: int = 20) -> list[str]:
        query = {term.lower() for term in objective.replace("/", " ").replace("_", " ").split() if len(term) > 2}
        ranked = [(len(query & terms), path) for path, terms in self.index.items()]
        return [path for score, path in sorted(ranked, reverse=True) if score > 0][:limit]


class LayeredMemory:
    def __init__(self, workspace: Path) -> None:
        root = workspace / ".amosclaud"
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / "foundation-memory.db"
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS memory(id TEXT PRIMARY KEY, layer TEXT, text TEXT, evidence TEXT, created_at TEXT)")

    def remember(self, layer: str, text: str, evidence: str = "") -> str:
        key = hashlib.sha256(f"{layer}:{text}".encode()).hexdigest()[:24]
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT OR REPLACE INTO memory VALUES(?,?,?,?,?)", (key, layer, text[:8000], evidence[:8000], datetime.now(timezone.utc).isoformat()))
        return key

    def recall(self, query: str, limit: int = 8) -> list[str]:
        terms = [term.lower() for term in query.split() if len(term) > 2]
        with sqlite3.connect(self.path) as db:
            rows = db.execute("SELECT text,evidence FROM memory ORDER BY created_at DESC LIMIT 250").fetchall()
        ranked = []
        for text, evidence in rows:
            score = sum(term in f"{text} {evidence}".lower() for term in terms)
            if score:
                ranked.append((score, text))
        return [text for _, text in sorted(ranked, reverse=True)[:limit]]

    def count(self) -> int:
        with sqlite3.connect(self.path) as db:
            return int(db.execute("SELECT COUNT(*) FROM memory").fetchone()[0])


class SimulationLab:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()

    def prepare(self, objective: str) -> dict[str, Any]:
        root = Path(tempfile.mkdtemp(prefix="amosclaud-sim-"))
        manifest = {"objective": objective, "source": str(self.workspace), "write_through": False}
        (root / "simulation.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return {"workspace": str(root), **manifest}


class SkillsRegistry:
    SKILLS = {
        "assistant": {"reply", "explain", "conversation", "assistant"},
        "python": {"python", "pytest", "fastapi"},
        "frontend": {"javascript", "html", "css", "react"},
        "codex": {"repository", "code", "debug", "test", "pull request"},
        "cloud": {"cloud", "railway", "deploy", "api", "webhook"},
        "security": {"security", "auth", "permission", "token", "owner"},
        "database": {"database", "sqlite", "postgres", "migration"},
        "self-healing": {"repair", "heal", "incident", "rollback"},
    }

    def required(self, objective: str) -> list[str]:
        lower = objective.lower()
        return sorted(skill for skill, words in self.SKILLS.items() if any(word in lower for word in words)) or ["assistant"]


class GovernanceEngine:
    ALWAYS_ALLOWED = {"observe", "analyze", "plan", "test", "report", "learn", "simulate", "practice"}
    OWNER_REQUIRED = {"write", "commit", "create_pr", "deploy", "rotate_key"}
    NEVER_ALLOWED = {"expose_secret", "delete_user_data", "transfer_founder_automatically"}

    def decide(self, requested: set[str], authorized_writes: bool, founder_verified: bool = False) -> tuple[list[str], list[str]]:
        allowed: list[str] = []
        blocked: list[str] = []
        for action in sorted(requested):
            if action in self.NEVER_ALLOWED:
                blocked.append(action)
            elif action in self.ALWAYS_ALLOWED:
                allowed.append(action)
            elif action in self.OWNER_REQUIRED and authorized_writes and founder_verified:
                allowed.append(action)
            else:
                blocked.append(action)
        return allowed, blocked


class MissionControl:
    def snapshot(self, context: FoundationContext, graph_files: int, memory_count: int) -> dict[str, Any]:
        return {
            "foundation_ready": True,
            "knowledge_graph_files": graph_files,
            "memory_records": memory_count,
            "confidence": context.confidence,
            "risk": context.risk,
            "skills": context.skills,
            "allowed_actions": context.allowed_actions,
            "blocked_actions": context.blocked_actions,
            "next_lesson": context.next_lesson,
        }


class IntelligentFoundation:
    """Combines all six systems into one decision context for Autonomous."""

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()
        self.graph = KnowledgeGraph(self.workspace)
        self.memory = LayeredMemory(self.workspace)
        self.simulation = SimulationLab(self.workspace)
        self.skills = SkillsRegistry()
        self.governance = GovernanceEngine()
        self.mission_control = MissionControl()
        self.curriculum = UniversalCurriculum()

    def prepare(self, objective: str, *, authorized_writes: bool = False, founder_verified: bool = False, current_level: int = 1) -> FoundationContext:
        self.graph.build()
        related = self.graph.related(objective)
        memories = self.memory.recall(objective)
        skills = self.skills.required(objective)
        requested = {"observe", "analyze", "plan", "test", "report", "learn", "practice"}
        risky = any(word in objective.lower() for word in ("fix", "write", "change", "commit", "deploy"))
        if risky:
            requested.update({"simulate", "write"})
        allowed, blocked = self.governance.decide(requested, authorized_writes, founder_verified)
        missing = [] if related or memories else ["No related repository evidence or verified memory was found"]
        confidence = min(0.98, 0.35 + min(len(related), 10) * 0.04 + min(len(memories), 5) * 0.05)
        risk = "high" if "deploy" in objective.lower() else "medium" if risky else "low"
        simulation = self.simulation.prepare(objective) if risky else None
        return FoundationContext(
            objective=objective,
            confidence=round(confidence, 2),
            risk=risk,
            related_files=related,
            memories=memories,
            skills=skills,
            allowed_actions=allowed,
            blocked_actions=blocked,
            missing_evidence=missing,
            next_lesson=self.curriculum.next_lesson(current_level),
            simulation=simulation,
        )

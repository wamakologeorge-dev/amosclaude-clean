#!/usr/bin/env python3
"""Create the required Amosclaud Autonomous OS foundation in one safe command.

Usage:
    python scripts/amosclaud_autonomous_required.py
    python scripts/amosclaud_autonomous_required.py --check
    python scripts/amosclaud_autonomous_required.py --force

The command is idempotent. Existing files are preserved unless --force is used.
Every generated component points back to the canonical Amosclaud OS kernel.
"""
from __future__ import annotations

import argparse
import py_compile
from pathlib import Path
from textwrap import dedent

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src" / "amosclaud_os" / "autonomy"

FILES: dict[str, str] = {
    "__init__.py": '''"""Required services governed by the single Amosclaud Autonomous kernel."""\nfrom .runtime import AutonomousRequiredRuntime\n\n__all__ = ["AutonomousRequiredRuntime"]\n''',
    "contracts.py": '''"""Shared contracts for real Autonomous work and evidence."""\nfrom __future__ import annotations\nfrom dataclasses import dataclass, field\nfrom typing import Any, Callable\n\n@dataclass(frozen=True)\nclass ToolResult:\n    tool: str\n    ok: bool\n    summary: str\n    evidence: list[str] = field(default_factory=list)\n    data: dict[str, Any] = field(default_factory=dict)\n\n@dataclass(frozen=True)\nclass ToolDefinition:\n    name: str\n    description: str\n    risk: str\n    handler: Callable[..., ToolResult]\n    requires_approval: bool = False\n\n@dataclass(frozen=True)\nclass VerificationResult:\n    contract: str\n    passed: bool\n    checks: list[ToolResult]\n''',
    "tool_registry.py": '''"""Approved tool registry; Autonomous never invents tools."""\nfrom __future__ import annotations\nfrom .contracts import ToolDefinition, ToolResult\n\nclass ToolRegistry:\n    def __init__(self) -> None:\n        self._tools: dict[str, ToolDefinition] = {}\n\n    def register(self, definition: ToolDefinition) -> None:\n        if definition.name in self._tools:\n            raise ValueError(f"Tool already registered: {definition.name}")\n        self._tools[definition.name] = definition\n\n    def describe(self) -> list[dict[str, object]]:\n        return [{"name": t.name, "description": t.description, "risk": t.risk, "requires_approval": t.requires_approval} for t in self._tools.values()]\n\n    def execute(self, name: str, *, approved: bool = False, **kwargs) -> ToolResult:\n        tool = self._tools.get(name)\n        if tool is None:\n            return ToolResult(name, False, "Unknown tool; execution refused.")\n        if tool.requires_approval and not approved:\n            return ToolResult(name, False, "Founder approval is required.")\n        try:\n            return tool.handler(**kwargs)\n        except Exception as exc:\n            return ToolResult(name, False, f"{type(exc).__name__}: {exc}")\n''',
    "mission_store.py": '''"""SQLite mission state that survives process restarts."""\nfrom __future__ import annotations\nimport json, sqlite3, uuid\nfrom datetime import datetime, timezone\nfrom pathlib import Path\nfrom typing import Any\n\nclass MissionStore:\n    def __init__(self, path: Path) -> None:\n        path.parent.mkdir(parents=True, exist_ok=True)\n        self.path = path\n        with self._connect() as db:\n            db.execute("CREATE TABLE IF NOT EXISTS missions (id TEXT PRIMARY KEY, objective TEXT NOT NULL, status TEXT NOT NULL, phase TEXT NOT NULL, payload TEXT NOT NULL, updated_at TEXT NOT NULL)")\n\n    def _connect(self):\n        return sqlite3.connect(self.path)\n\n    def create(self, objective: str, payload: dict[str, Any] | None = None) -> str:\n        mission_id = str(uuid.uuid4())\n        self.update(mission_id, objective, "queued", "receive", payload or {})\n        return mission_id\n\n    def update(self, mission_id: str, objective: str, status: str, phase: str, payload: dict[str, Any]) -> None:\n        now = datetime.now(timezone.utc).isoformat()\n        with self._connect() as db:\n            db.execute("INSERT INTO missions VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET objective=excluded.objective,status=excluded.status,phase=excluded.phase,payload=excluded.payload,updated_at=excluded.updated_at", (mission_id, objective, status, phase, json.dumps(payload), now))\n\n    def get(self, mission_id: str) -> dict[str, Any]:\n        with self._connect() as db:\n            row = db.execute("SELECT id,objective,status,phase,payload,updated_at FROM missions WHERE id=?", (mission_id,)).fetchone()\n        if row is None:\n            raise KeyError(mission_id)\n        return {"id": row[0], "objective": row[1], "status": row[2], "phase": row[3], "payload": json.loads(row[4]), "updated_at": row[5]}\n''',
    "verification_contracts.py": '''"""Explicit definitions of success for Autonomous jobs."""\nfrom __future__ import annotations\nfrom collections.abc import Callable\nfrom .contracts import ToolResult, VerificationResult\n\nclass VerificationContracts:\n    def __init__(self) -> None:\n        self._contracts: dict[str, list[tuple[str, Callable[[], ToolResult]]]] = {}\n\n    def register(self, name: str, checks: list[tuple[str, Callable[[], ToolResult]]]) -> None:\n        if not checks:\n            raise ValueError("A verification contract requires at least one check")\n        self._contracts[name] = checks\n\n    def run(self, name: str) -> VerificationResult:\n        checks = self._contracts.get(name)\n        if checks is None:\n            return VerificationResult(name, False, [ToolResult("contract", False, "Verification contract is not registered.")])\n        results = [check() for _, check in checks]\n        return VerificationResult(name, all(item.ok for item in results), results)\n''',
    "recovery_doctor.py": '''"""Classify failures and select bounded, safe recovery actions."""\nfrom __future__ import annotations\nfrom dataclasses import dataclass\n\n@dataclass(frozen=True)\nclass RecoveryDecision:\n    category: str\n    action: str\n    retryable: bool\n    max_attempts: int\n\nclass RecoveryDoctor:\n    RULES = {\n        "AssertionError": RecoveryDecision("verification", "inspect assertion evidence and repair the smallest cause", True, 2),\n        "TimeoutError": RecoveryDecision("temporary-runtime", "retry with bounded timeout and alternate route", True, 2),\n        "PermissionError": RecoveryDecision("authorization", "request founder approval; never bypass permissions", False, 0),\n        "ConnectionError": RecoveryDecision("connector", "check connector health and use configured fallback", True, 2),\n    }\n\n    def diagnose(self, error: BaseException) -> RecoveryDecision:\n        return self.RULES.get(type(error).__name__, RecoveryDecision("unknown", "stop safely and report exact evidence", False, 0))\n''',
    "event_stream.py": '''"""Backend event stream for the Live Autonomous Workbench."""\nfrom __future__ import annotations\nfrom collections import defaultdict, deque\nfrom datetime import datetime, timezone\nfrom threading import RLock\nfrom typing import Any\n\nclass EventStream:\n    def __init__(self, limit: int = 1000) -> None:\n        self.limit = limit\n        self._events: dict[str, deque[dict[str, Any]]] = defaultdict(lambda: deque(maxlen=limit))\n        self._lock = RLock()\n\n    def publish(self, mission_id: str, event: str, **data: Any) -> dict[str, Any]:\n        item = {"mission_id": mission_id, "event": event, "time": datetime.now(timezone.utc).isoformat(), "data": data}\n        with self._lock:\n            self._events[mission_id].append(item)\n        return item\n\n    def read(self, mission_id: str, after: int = 0) -> list[dict[str, Any]]:\n        with self._lock:\n            return list(self._events.get(mission_id, ()))[max(0, after):]\n''',
    "model_router.py": '''"""Route model jobs while Autonomous remains the sole controller."""\nfrom __future__ import annotations\nfrom dataclasses import dataclass\n\n@dataclass(frozen=True)\nclass ModelTarget:\n    name: str\n    purpose: str\n    priority: int = 100\n\nclass ModelRouter:\n    def __init__(self) -> None:\n        self._targets: dict[str, list[ModelTarget]] = {}\n\n    def register(self, capability: str, target: ModelTarget) -> None:\n        self._targets.setdefault(capability, []).append(target)\n        self._targets[capability].sort(key=lambda item: item.priority)\n\n    def route(self, capability: str, unavailable: set[str] | None = None) -> ModelTarget | None:\n        blocked = unavailable or set()\n        return next((target for target in self._targets.get(capability, []) if target.name not in blocked), None)\n''',
    "memory_store.py": '''"""Layered memory that promotes only verified outcomes."""\nfrom __future__ import annotations\nimport json, sqlite3\nfrom datetime import datetime, timezone\nfrom pathlib import Path\nfrom typing import Any\n\nclass LayeredMemory:\n    VALID = {"working", "mission", "project", "lesson", "long_term"}\n    def __init__(self, path: Path) -> None:\n        path.parent.mkdir(parents=True, exist_ok=True)\n        self.path = path\n        with sqlite3.connect(path) as db:\n            db.execute("CREATE TABLE IF NOT EXISTS memories (layer TEXT, key TEXT, value TEXT, verified INTEGER, created_at TEXT, PRIMARY KEY(layer,key))")\n\n    def put(self, layer: str, key: str, value: dict[str, Any], *, verified: bool = False) -> None:\n        if layer not in self.VALID:\n            raise ValueError(f"Invalid memory layer: {layer}")\n        if layer in {"lesson", "long_term"} and not verified:\n            raise PermissionError("Trusted lessons and long-term memory require verified evidence")\n        with sqlite3.connect(self.path) as db:\n            db.execute("INSERT OR REPLACE INTO memories VALUES (?,?,?,?,?)", (layer, key, json.dumps(value), int(verified), datetime.now(timezone.utc).isoformat()))\n''',
    "worker.py": '''"""Bounded background mission worker with lease semantics."""\nfrom __future__ import annotations\nfrom dataclasses import dataclass\nfrom datetime import datetime, timedelta, timezone\nfrom threading import RLock\n\n@dataclass\nclass Lease:\n    mission_id: str\n    worker_id: str\n    expires_at: datetime\n\nclass WorkerLeases:\n    def __init__(self) -> None:\n        self._leases: dict[str, Lease] = {}\n        self._lock = RLock()\n\n    def acquire(self, mission_id: str, worker_id: str, seconds: int = 60) -> bool:\n        now = datetime.now(timezone.utc)\n        with self._lock:\n            current = self._leases.get(mission_id)\n            if current and current.expires_at > now and current.worker_id != worker_id:\n                return False\n            self._leases[mission_id] = Lease(mission_id, worker_id, now + timedelta(seconds=max(5, seconds)))\n            return True\n\n    def release(self, mission_id: str, worker_id: str) -> None:\n        with self._lock:\n            current = self._leases.get(mission_id)\n            if current and current.worker_id == worker_id:\n                self._leases.pop(mission_id, None)\n''',
    "connectors.py": '''"""Health-aware connector registry for Amosclaud, GitHub, Railway and models."""\nfrom __future__ import annotations\nfrom dataclasses import dataclass\nfrom typing import Callable\n\n@dataclass(frozen=True)\nclass Connector:\n    name: str\n    healthcheck: Callable[[], bool]\n    permissions: frozenset[str]\n\nclass ConnectorRegistry:\n    def __init__(self) -> None:\n        self._items: dict[str, Connector] = {}\n\n    def register(self, connector: Connector) -> None:\n        self._items[connector.name] = connector\n\n    def status(self) -> dict[str, dict[str, object]]:\n        result = {}\n        for name, connector in self._items.items():\n            try:\n                healthy = bool(connector.healthcheck())\n            except Exception:\n                healthy = False\n            result[name] = {"healthy": healthy, "permissions": sorted(connector.permissions)}\n        return result\n''',
    "audit_replay.py": '''"""Append-only audit records used by the Living Engineering Timeline."""\nfrom __future__ import annotations\nimport json\nfrom datetime import datetime, timezone\nfrom pathlib import Path\nfrom threading import RLock\nfrom typing import Any\n\nclass AuditReplay:\n    def __init__(self, path: Path) -> None:\n        path.parent.mkdir(parents=True, exist_ok=True)\n        self.path = path\n        self._lock = RLock()\n\n    def append(self, mission_id: str, action: str, evidence: dict[str, Any]) -> None:\n        record = {"mission_id": mission_id, "action": action, "evidence": evidence, "time": datetime.now(timezone.utc).isoformat()}\n        with self._lock, self.path.open("a", encoding="utf-8") as handle:\n            handle.write(json.dumps(record, sort_keys=True) + "\\n")\n\n    def replay(self, mission_id: str) -> list[dict[str, Any]]:\n        if not self.path.exists():\n            return []\n        return [item for item in (json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()) if item.get("mission_id") == mission_id]\n''',
    "runtime.py": '''"""Composition root for required services behind the single OS kernel."""\nfrom __future__ import annotations\nimport os\nfrom pathlib import Path\nfrom src.amosclaud_os.kernel import get_autonomous_kernel\nfrom .audit_replay import AuditReplay\nfrom .connectors import ConnectorRegistry\nfrom .event_stream import EventStream\nfrom .memory_store import LayeredMemory\nfrom .mission_store import MissionStore\nfrom .model_router import ModelRouter\nfrom .recovery_doctor import RecoveryDoctor\nfrom .tool_registry import ToolRegistry\nfrom .verification_contracts import VerificationContracts\nfrom .worker import WorkerLeases\n\nclass AutonomousRequiredRuntime:\n    def __init__(self, workspace: str | Path = ".") -> None:\n        self.workspace = Path(workspace).resolve()\n        data = Path(os.getenv("AMOSCLAUD_AUTONOMY_DATA", self.workspace / ".amosclaud" / "autonomy"))\n        self.kernel = get_autonomous_kernel(self.workspace)\n        self.tools = ToolRegistry()\n        self.missions = MissionStore(data / "missions.db")\n        self.verification = VerificationContracts()\n        self.doctor = RecoveryDoctor()\n        self.events = EventStream()\n        self.models = ModelRouter()\n        self.memory = LayeredMemory(data / "memory.db")\n        self.workers = WorkerLeases()\n        self.connectors = ConnectorRegistry()\n        self.audit = AuditReplay(data / "audit.jsonl")\n\n    def status(self) -> dict[str, object]:\n        return {"status": "ready", "single_source": self.kernel.status()["single_source"], "workspace": str(self.workspace), "services": ["tools", "missions", "verification", "doctor", "events", "models", "memory", "workers", "connectors", "audit"]}\n''',
}


def write_files(force: bool) -> tuple[list[Path], list[Path]]:
    created: list[Path] = []
    preserved: list[Path] = []
    PACKAGE.mkdir(parents=True, exist_ok=True)
    for relative, content in FILES.items():
        target = PACKAGE / relative
        if target.exists() and not force:
            preserved.append(target)
            continue
        target.write_text(dedent(content).lstrip(), encoding="utf-8")
        created.append(target)
    return created, preserved


def compile_files() -> list[str]:
    failures: list[str] = []
    for relative in FILES:
        path = PACKAGE / relative
        if not path.exists():
            failures.append(f"missing: {path.relative_to(ROOT)}")
            continue
        try:
            py_compile.compile(str(path), doraise=True)
        except py_compile.PyCompileError as exc:
            failures.append(str(exc))
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Create and validate the Amosclaud Autonomous required foundation.")
    parser.add_argument("--force", action="store_true", help="Replace previously generated files.")
    parser.add_argument("--check", action="store_true", help="Validate only; do not write files.")
    args = parser.parse_args()

    created: list[Path] = []
    preserved: list[Path] = []
    if not args.check:
        created, preserved = write_files(args.force)

    failures = compile_files()
    print("AMOSCLAUD AUTONOMOUS REQUIRED")
    print(f"Canonical source: src.amosclaud_os.kernel.AutonomousKernel")
    print(f"Created or updated: {len(created)}")
    print(f"Preserved: {len(preserved)}")
    for path in created:
        print(f"  WRITE {path.relative_to(ROOT)}")
    for failure in failures:
        print(f"  FAIL {failure}")
    if failures:
        return 1
    print(f"PASS: {len(FILES)} required files are present and compile successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

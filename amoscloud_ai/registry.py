"""Durable metadata registry for trusted Amosclaud capabilities and clients.

The Registry is discovery metadata only. It never imports or executes code from a
registry entry, and it does not create a second autonomous identity or runtime.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

REGISTRY_SCHEMA_VERSION = 1
REGISTRY_KINDS = {"capability", "client", "service", "skill", "adapter"}
REGISTRY_STATUSES = {"active", "experimental", "deprecated", "disabled"}
REGISTRY_TRUST_LEVELS = {"first-party", "approved", "community"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _entry(
    entry_id: str,
    *,
    kind: str,
    title: str,
    description: str,
    version: str,
    entrypoint: str,
    capabilities: Iterable[str],
    platforms: Iterable[str],
    status: str = "active",
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": entry_id,
        "kind": kind,
        "title": title,
        "description": description,
        "version": version,
        "status": status,
        "trust": "first-party",
        "entrypoint": entrypoint,
        "source_url": "https://github.com/wamakologeorge-dev/amosclaude-clean",
        "capabilities": sorted(set(capabilities)),
        "platforms": sorted(set(platforms)),
        "metadata": dict(metadata or {}),
        "immutable": True,
    }


BUILTIN_ENTRIES: tuple[dict[str, Any], ...] = (
    _entry(
        "capability.autonomous",
        kind="capability",
        title="Autonomous orchestration",
        description=(
            "Plans and coordinates bounded repository work through the canonical "
            "Amosclaud Autonomous pipeline."
        ),
        version="1.0",
        entrypoint="/api/v1/copilot/run",
        capabilities=(
            "planning",
            "repository-execution",
            "deployment",
            "monitoring",
            "evidence-reporting",
        ),
        platforms=("api", "cli", "vscode", "xcode", "web"),
        metadata={"internal_role": "amosclaud-autonomous"},
    ),
    _entry(
        "capability.codex",
        kind="capability",
        title="Code implementation",
        description="Understands code and prepares repository-aware software changes.",
        version="1.0",
        entrypoint="/api/v1/copilot/plan",
        capabilities=("code-generation", "code-explanation", "refactoring", "review"),
        platforms=("api", "cli", "vscode", "xcode", "web"),
        metadata={"internal_role": "amosclaud-codex-agent"},
    ),
    _entry(
        "capability.fixer",
        kind="capability",
        title="Verified repair",
        description="Diagnoses verified failures and prepares the smallest safe repair.",
        version="1.0",
        entrypoint="/api/v1/copilot/plan",
        capabilities=("bug-fix", "failure-diagnosis", "regression-repair", "verification"),
        platforms=("api", "cli", "vscode", "xcode", "web"),
        metadata={"internal_role": "amosclaud-fixer"},
    ),
    _entry(
        "capability.action",
        kind="capability",
        title="Tests and repository automation",
        description="Prepares tests, CI workflows, GitHub Actions, and repeatable automation.",
        version="1.0",
        entrypoint="/api/v1/copilot/plan",
        capabilities=("tests", "github-actions", "ci", "automation"),
        platforms=("api", "cli", "vscode", "xcode", "web"),
        metadata={"internal_role": "amosclaud-action"},
    ),
    _entry(
        "capability.security",
        kind="capability",
        title="Security review",
        description="Reviews authentication, authorization, secrets, and dependency risk.",
        version="1.0",
        entrypoint="/api/v1/copilot/plan",
        capabilities=("security-review", "auth-review", "secret-safety", "dependency-risk"),
        platforms=("api", "cli", "vscode", "xcode", "web"),
        metadata={"internal_role": "amosclaud-security"},
    ),
    _entry(
        "capability.clean",
        kind="capability",
        title="Code quality",
        description="Improves lint, formatting, duplication, and maintainability safely.",
        version="1.0",
        entrypoint="/api/v1/copilot/plan",
        capabilities=("lint", "format", "cleanup", "deduplication", "maintainability"),
        platforms=("api", "cli", "vscode", "xcode", "web"),
        metadata={"internal_role": "amosclaud-clean"},
    ),
    _entry(
        "capability.ai",
        kind="capability",
        title="Technical chat and requirements",
        description="Explains technical systems and turns developer intent into an objective.",
        version="1.0",
        entrypoint="/api/v1/copilot/plan",
        capabilities=("technical-chat", "requirements", "explanation", "planning"),
        platforms=("api", "cli", "vscode", "xcode", "web"),
        metadata={"internal_role": "amosclaud-ai-agent"},
    ),
    _entry(
        "client.ide-cli",
        kind="client",
        title="Portable IDE CLI",
        description="Dependency-free terminal and editor adapter for plan, run, and chat.",
        version="0.1.0",
        entrypoint="amosclaud-ide",
        capabilities=("doctor", "discovery", "plan", "run", "chat"),
        platforms=("linux", "macos", "windows", "terminal"),
    ),
    _entry(
        "client.vscode",
        kind="client",
        title="VS Code companion",
        description="VS Code chat panel with secure token storage and bounded context.",
        version="0.1.0",
        entrypoint="clients/vscode-amosclaud",
        capabilities=("discovery", "plan", "run", "chat", "editor-context"),
        platforms=("linux", "macos", "windows", "vscode"),
    ),
    _entry(
        "client.xcode",
        kind="client",
        title="Xcode companion",
        description="Native Swift companion with Keychain lookup and Xcode behavior support.",
        version="0.1.0",
        entrypoint="clients/xcode-amosclaud",
        capabilities=("discovery", "plan", "run", "chat", "editor-context"),
        platforms=("macos", "xcode"),
    ),
    _entry(
        "service.copilot-api",
        kind="service",
        title="Copilot routing API",
        description="Repository-aware planning and governed Autonomous execution adapter.",
        version="1.0",
        entrypoint="/api/v1/copilot",
        capabilities=("agent-discovery", "routing", "plan", "run"),
        platforms=("api", "web"),
    ),
    _entry(
        "service.node-control-plane",
        kind="service",
        title="Node.js asynchronous control plane",
        description="Private durable task queue, workers, watchers, logs, and runtime lifecycle API.",
        version="0.1.0",
        entrypoint="services/control_plane",
        capabilities=("task-queue", "worker", "watcher", "logs", "runtime-lifecycle"),
        platforms=("linux", "macos", "nodejs", "server"),
    ),
)


def manifest_digest(entry: Mapping[str, Any]) -> str:
    """Return a deterministic metadata digest; this is not an artifact signature."""

    stable = {
        key: entry.get(key)
        for key in (
            "id",
            "kind",
            "title",
            "description",
            "version",
            "status",
            "trust",
            "entrypoint",
            "source_url",
            "capabilities",
            "platforms",
            "metadata",
            "immutable",
        )
    }
    encoded = json.dumps(stable, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def ensure_registry_schema(db: sqlite3.Connection) -> None:
    db.row_factory = sqlite3.Row
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS amosclaud_registry_entries (
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            version TEXT NOT NULL,
            status TEXT NOT NULL,
            trust TEXT NOT NULL,
            entrypoint TEXT NOT NULL,
            source_url TEXT,
            capabilities_json TEXT NOT NULL,
            platforms_json TEXT NOT NULL,
            metadata_json TEXT NOT NULL,
            immutable INTEGER NOT NULL DEFAULT 0,
            manifest_digest TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            created_by INTEGER
        )
        """
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_registry_kind_status "
        "ON amosclaud_registry_entries(kind,status)"
    )
    db.commit()


def _database_values(entry: Mapping[str, Any], *, created_at: str, updated_at: str) -> tuple[Any, ...]:
    complete = dict(entry)
    complete.setdefault("source_url", None)
    complete.setdefault("capabilities", [])
    complete.setdefault("platforms", [])
    complete.setdefault("metadata", {})
    complete.setdefault("immutable", False)
    return (
        complete["id"],
        complete["kind"],
        complete["title"],
        complete["description"],
        complete["version"],
        complete["status"],
        complete["trust"],
        complete["entrypoint"],
        complete["source_url"],
        json.dumps(sorted(set(complete["capabilities"]))),
        json.dumps(sorted(set(complete["platforms"]))),
        json.dumps(complete["metadata"], sort_keys=True),
        int(bool(complete["immutable"])),
        manifest_digest(complete),
        created_at,
        updated_at,
        complete.get("created_by"),
    )


def seed_builtin_entries(db: sqlite3.Connection) -> None:
    ensure_registry_schema(db)
    now = _now()
    for entry in BUILTIN_ENTRIES:
        existing = db.execute(
            "SELECT created_at FROM amosclaud_registry_entries WHERE id=?",
            (entry["id"],),
        ).fetchone()
        created_at = str(existing["created_at"]) if existing else now
        db.execute(
            """
            INSERT INTO amosclaud_registry_entries(
                id,kind,title,description,version,status,trust,entrypoint,source_url,
                capabilities_json,platforms_json,metadata_json,immutable,manifest_digest,
                created_at,updated_at,created_by
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
                kind=excluded.kind,
                title=excluded.title,
                description=excluded.description,
                version=excluded.version,
                status=excluded.status,
                trust=excluded.trust,
                entrypoint=excluded.entrypoint,
                source_url=excluded.source_url,
                capabilities_json=excluded.capabilities_json,
                platforms_json=excluded.platforms_json,
                metadata_json=excluded.metadata_json,
                immutable=1,
                manifest_digest=excluded.manifest_digest,
                updated_at=excluded.updated_at
            """,
            _database_values(entry, created_at=created_at, updated_at=now),
        )
    db.commit()


def _decode_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "kind": row["kind"],
        "title": row["title"],
        "description": row["description"],
        "version": row["version"],
        "status": row["status"],
        "trust": row["trust"],
        "entrypoint": row["entrypoint"],
        "source_url": row["source_url"],
        "capabilities": json.loads(row["capabilities_json"]),
        "platforms": json.loads(row["platforms_json"]),
        "metadata": json.loads(row["metadata_json"]),
        "immutable": bool(row["immutable"]),
        "manifest_digest": row["manifest_digest"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def list_entries(
    db: sqlite3.Connection,
    *,
    kind: str | None = None,
    status: str | None = None,
    capability: str | None = None,
    platform: str | None = None,
    include_disabled: bool = False,
) -> list[dict[str, Any]]:
    seed_builtin_entries(db)
    clauses: list[str] = []
    parameters: list[Any] = []
    if kind:
        clauses.append("kind=?")
        parameters.append(kind)
    if status:
        clauses.append("status=?")
        parameters.append(status)
    elif not include_disabled:
        clauses.append("status!='disabled'")
    if capability:
        clauses.append("EXISTS (SELECT 1 FROM json_each(capabilities_json) WHERE value=?)")
        parameters.append(capability)
    if platform:
        clauses.append("EXISTS (SELECT 1 FROM json_each(platforms_json) WHERE value=?)")
        parameters.append(platform)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = db.execute(
        "SELECT * FROM amosclaud_registry_entries" + where + " ORDER BY kind,title,id",
        parameters,
    ).fetchall()
    return [_decode_row(row) for row in rows]


def get_entry(db: sqlite3.Connection, entry_id: str) -> dict[str, Any] | None:
    seed_builtin_entries(db)
    row = db.execute(
        "SELECT * FROM amosclaud_registry_entries WHERE id=?",
        (entry_id,),
    ).fetchone()
    return _decode_row(row) if row else None


def create_entry(db: sqlite3.Connection, entry: Mapping[str, Any], *, created_by: int) -> dict[str, Any]:
    seed_builtin_entries(db)
    if db.execute("SELECT 1 FROM amosclaud_registry_entries WHERE id=?", (entry["id"],)).fetchone():
        raise ValueError("Registry entry already exists")
    complete = dict(entry)
    complete["immutable"] = False
    complete["created_by"] = created_by
    now = _now()
    db.execute(
        """
        INSERT INTO amosclaud_registry_entries(
            id,kind,title,description,version,status,trust,entrypoint,source_url,
            capabilities_json,platforms_json,metadata_json,immutable,manifest_digest,
            created_at,updated_at,created_by
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        _database_values(complete, created_at=now, updated_at=now),
    )
    db.commit()
    created = get_entry(db, str(entry["id"]))
    assert created is not None
    return created


def update_entry(
    db: sqlite3.Connection,
    entry_id: str,
    changes: Mapping[str, Any],
) -> dict[str, Any]:
    existing = get_entry(db, entry_id)
    if not existing:
        raise KeyError(entry_id)
    if existing["immutable"]:
        raise PermissionError("First-party registry entries are immutable")
    merged = dict(existing)
    merged.update({key: value for key, value in changes.items() if value is not None})
    merged["id"] = entry_id
    merged["immutable"] = False
    now = _now()
    values = _database_values(merged, created_at=existing["created_at"], updated_at=now)
    db.execute(
        """
        UPDATE amosclaud_registry_entries SET
            kind=?,title=?,description=?,version=?,status=?,trust=?,entrypoint=?,source_url=?,
            capabilities_json=?,platforms_json=?,metadata_json=?,immutable=?,manifest_digest=?,
            created_at=?,updated_at=?,created_by=?
        WHERE id=?
        """,
        values[1:] + (entry_id,),
    )
    db.commit()
    updated = get_entry(db, entry_id)
    assert updated is not None
    return updated


def disable_entry(db: sqlite3.Connection, entry_id: str) -> dict[str, Any]:
    return update_entry(db, entry_id, {"status": "disabled"})


def registry_summary(db: sqlite3.Connection) -> dict[str, Any]:
    entries = list_entries(db, include_disabled=False)
    counts: dict[str, int] = {kind: 0 for kind in sorted(REGISTRY_KINDS)}
    for entry in entries:
        counts[entry["kind"]] = counts.get(entry["kind"], 0) + 1
    capabilities = sorted(
        {capability for entry in entries for capability in entry.get("capabilities", [])}
    )
    platforms = sorted({platform for entry in entries for platform in entry.get("platforms", [])})
    return {
        "schema_version": REGISTRY_SCHEMA_VERSION,
        "identity": {"name": "Amosclaud Autonomous", "type": "one-agent"},
        "entry_count": len(entries),
        "counts": counts,
        "capabilities": capabilities,
        "platforms": platforms,
        "generated_at": _now(),
    }

"""Safety-first persistent control plane for Amosclaud SentinelGrid."""

from __future__ import annotations

import json
import math
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Iterator
from uuid import uuid4

ConnectionFactory = Callable[[], sqlite3.Connection]
MetricValue = float | int | bool | str


class AssetType(str, Enum):
    ROBOT = "robot"
    AUTONOMOUS_VEHICLE = "autonomous_vehicle"
    EDGE_NODE = "edge_node"
    CHARGING_STATION = "charging_station"
    SENSOR = "sensor"


class RiskLevel(str, Enum):
    LOW = "low"
    ELEVATED = "elevated"
    CRITICAL = "critical"


class IncidentStatus(str, Enum):
    OPEN = "open"
    RESOLVED = "resolved"


class ActionStatus(str, Enum):
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"


class SentinelGridError(RuntimeError):
    """Base error for invalid SentinelGrid operations."""


class InvalidInputError(SentinelGridError):
    """Raised when normalized input is empty, invalid, or unsafe."""


class AssetNotFoundError(SentinelGridError):
    """Raised when an asset identifier is unknown."""


class ActionNotFoundError(SentinelGridError):
    """Raised when an action proposal identifier is unknown."""


class StateConflictError(SentinelGridError):
    """Raised when a requested transition or asset action is not allowed."""


@dataclass(frozen=True, slots=True)
class AssetRecord:
    asset_id: str
    name: str
    asset_type: AssetType
    site: str
    capabilities: tuple[str, ...]
    registered_at: datetime


@dataclass(frozen=True, slots=True)
class IncidentRecord:
    incident_id: str
    asset_id: str
    code: str
    risk: RiskLevel
    status: IncidentStatus
    message: str
    recommended_action: str
    occurrence_count: int
    created_at: datetime
    last_seen_at: datetime
    resolved_at: datetime | None


@dataclass(frozen=True, slots=True)
class TelemetryRecord:
    telemetry_id: str
    asset_id: str
    metrics: dict[str, MetricValue]
    observed_at: datetime
    received_at: datetime
    incident_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ActionProposal:
    action_id: str
    asset_id: str
    action_type: str
    reason: str
    requested_by: str
    risk: RiskLevel
    status: ActionStatus
    software_only: bool
    execution_allowed: bool
    created_at: datetime
    decided_at: datetime | None = None
    decided_by: str | None = None
    decision_note: str = ""


@dataclass(frozen=True, slots=True)
class _Finding:
    code: str
    risk: RiskLevel
    message: str
    recommended_action: str


class SentinelGridControlPlane:
    """Persist and supervise assets without directly commanding hardware."""

    SOFTWARE_ONLY_ACTIONS = frozenset({"analyze_telemetry", "inspect", "simulate"})
    CONTROLLED_ACTIONS = frozenset(
        {"emergency_shutdown", "move", "request_maintenance", "schedule_charge"}
    )
    ALLOWED_ACTIONS = SOFTWARE_ONLY_ACTIONS | CONTROLLED_ACTIONS
    ACTION_ASSET_TYPES = {
        "emergency_shutdown": frozenset(
            {
                AssetType.ROBOT,
                AssetType.AUTONOMOUS_VEHICLE,
                AssetType.EDGE_NODE,
                AssetType.CHARGING_STATION,
            }
        ),
        "move": frozenset({AssetType.ROBOT, AssetType.AUTONOMOUS_VEHICLE}),
        "request_maintenance": frozenset(AssetType),
        "schedule_charge": frozenset(
            {
                AssetType.ROBOT,
                AssetType.AUTONOMOUS_VEHICLE,
                AssetType.CHARGING_STATION,
            }
        ),
    }
    TELEMETRY_LIMIT = 5000

    def __init__(self, connection_factory: ConnectionFactory | None = None) -> None:
        self._lock = RLock()
        self._connection_factory = connection_factory or self._default_connection
        self.ensure_schema()

    @staticmethod
    def _default_connection() -> sqlite3.Connection:
        configured = os.getenv("SENTINELGRID_DB_PATH") or os.getenv("AUTH_DB_PATH", "data/auth.db")
        path = Path(configured)
        path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(path)
        db.row_factory = sqlite3.Row
        return db

    @contextmanager
    def _database(self) -> Iterator[sqlite3.Connection]:
        db = self._connection_factory()
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def ensure_schema(self) -> None:
        """Create all durable tables and indexes idempotently."""

        with self._lock, self._database() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS sentinelgrid_assets (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    asset_type TEXT NOT NULL,
                    site TEXT NOT NULL,
                    capabilities_json TEXT NOT NULL DEFAULT '[]',
                    registered_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sentinelgrid_incidents (
                    id TEXT PRIMARY KEY,
                    asset_id TEXT NOT NULL,
                    code TEXT NOT NULL,
                    risk TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('open','resolved')),
                    message TEXT NOT NULL,
                    recommended_action TEXT NOT NULL,
                    occurrence_count INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    resolved_at TEXT,
                    FOREIGN KEY(asset_id) REFERENCES sentinelgrid_assets(id)
                        ON DELETE CASCADE
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_sentinelgrid_incident_open
                    ON sentinelgrid_incidents(asset_id, code) WHERE status='open';
                CREATE INDEX IF NOT EXISTS idx_sentinelgrid_incident_status_seen
                    ON sentinelgrid_incidents(status, last_seen_at DESC);
                CREATE TABLE IF NOT EXISTS sentinelgrid_telemetry (
                    id TEXT PRIMARY KEY,
                    asset_id TEXT NOT NULL,
                    metrics_json TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    received_at TEXT NOT NULL,
                    incident_ids_json TEXT NOT NULL DEFAULT '[]',
                    FOREIGN KEY(asset_id) REFERENCES sentinelgrid_assets(id)
                        ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_sentinelgrid_telemetry_asset_received
                    ON sentinelgrid_telemetry(asset_id, received_at DESC);
                CREATE TABLE IF NOT EXISTS sentinelgrid_actions (
                    id TEXT PRIMARY KEY,
                    asset_id TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    requested_by TEXT NOT NULL,
                    risk TEXT NOT NULL,
                    status TEXT NOT NULL,
                    software_only INTEGER NOT NULL,
                    execution_allowed INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    decided_at TEXT,
                    decided_by TEXT,
                    decision_note TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY(asset_id) REFERENCES sentinelgrid_assets(id)
                        ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_sentinelgrid_actions_created
                    ON sentinelgrid_actions(created_at DESC);
                """)

    def reset(self) -> None:
        """Delete SentinelGrid data. Intended for isolated tests only."""

        self.ensure_schema()
        with self._lock, self._database() as db:
            for table in (
                "sentinelgrid_actions",
                "sentinelgrid_telemetry",
                "sentinelgrid_incidents",
                "sentinelgrid_assets",
            ):
                db.execute(f"DELETE FROM {table}")

    def status(self) -> dict[str, Any]:
        with self._lock, self._database() as db:
            counts = {
                "assets": self._count(db, "sentinelgrid_assets"),
                "telemetry_records": self._count(db, "sentinelgrid_telemetry"),
                "open_incidents": self._count(db, "sentinelgrid_incidents", "status='open'"),
                "action_proposals": self._count(db, "sentinelgrid_actions"),
            }
        return {
            "program": "Amosclaud SentinelGrid",
            "purpose": "Industrial autonomy supervision and safety control plane",
            "workflow": [
                "observe",
                "diagnose",
                "simulate",
                "recommend",
                "approve",
                "dispatch",
                "verify",
            ],
            "physical_execution": "disabled_without_external_approved_adapter",
            "state_storage": "persistent_sqlite",
            **counts,
        }

    def register_asset(
        self,
        *,
        name: str,
        asset_type: AssetType,
        site: str,
        capabilities: tuple[str, ...],
    ) -> AssetRecord:
        asset = AssetRecord(
            asset_id=f"asset-{uuid4().hex[:16]}",
            name=self._required_text(name, "Asset name", 2),
            asset_type=AssetType(asset_type),
            site=self._required_text(site, "Asset site", 2),
            capabilities=tuple(
                sorted({item.strip().lower() for item in capabilities if item.strip()})
            ),
            registered_at=self._now(),
        )
        with self._lock, self._database() as db:
            db.execute(
                """INSERT INTO sentinelgrid_assets
                   (id,name,asset_type,site,capabilities_json,registered_at)
                   VALUES (?,?,?,?,?,?)""",
                (
                    asset.asset_id,
                    asset.name,
                    asset.asset_type.value,
                    asset.site,
                    json.dumps(asset.capabilities),
                    self._iso(asset.registered_at),
                ),
            )
        return asset

    def list_assets(self, *, limit: int = 500) -> list[AssetRecord]:
        with self._lock, self._database() as db:
            rows = db.execute(
                "SELECT * FROM sentinelgrid_assets ORDER BY registered_at LIMIT ?",
                (self._limit(limit, 500),),
            ).fetchall()
        return [self._asset(row) for row in rows]

    def record_telemetry(
        self,
        *,
        asset_id: str,
        metrics: dict[str, MetricValue],
        observed_at: datetime | None = None,
    ) -> tuple[TelemetryRecord, list[IncidentRecord]]:
        if not metrics:
            raise InvalidInputError("Telemetry metrics cannot be empty")
        findings, evaluated_codes = self._diagnose(dict(metrics))
        received_at = self._now()
        with self._lock, self._database() as db:
            self._require_asset(db, asset_id)
            incidents = [
                self._upsert_incident(db, asset_id, finding, received_at) for finding in findings
            ]
            active_codes = {item.code for item in incidents}
            resolved_codes = evaluated_codes - active_codes
            if resolved_codes:
                marks = ",".join("?" for _ in resolved_codes)
                db.execute(
                    f"""UPDATE sentinelgrid_incidents
                        SET status='resolved', resolved_at=?
                        WHERE asset_id=? AND status='open' AND code IN ({marks})""",
                    (self._iso(received_at), asset_id, *sorted(resolved_codes)),
                )
            telemetry = TelemetryRecord(
                telemetry_id=f"telemetry-{uuid4().hex[:16]}",
                asset_id=asset_id,
                metrics=dict(metrics),
                observed_at=self._aware(observed_at or received_at),
                received_at=received_at,
                incident_ids=tuple(item.incident_id for item in incidents),
            )
            db.execute(
                """INSERT INTO sentinelgrid_telemetry
                   (id,asset_id,metrics_json,observed_at,received_at,incident_ids_json)
                   VALUES (?,?,?,?,?,?)""",
                (
                    telemetry.telemetry_id,
                    telemetry.asset_id,
                    json.dumps(telemetry.metrics, sort_keys=True),
                    self._iso(telemetry.observed_at),
                    self._iso(telemetry.received_at),
                    json.dumps(telemetry.incident_ids),
                ),
            )
            db.execute(
                """DELETE FROM sentinelgrid_telemetry WHERE id IN (
                       SELECT id FROM sentinelgrid_telemetry
                       ORDER BY received_at DESC LIMIT -1 OFFSET ?
                   )""",
                (self.TELEMETRY_LIMIT,),
            )
        return telemetry, incidents

    def list_incidents(
        self,
        *,
        limit: int = 100,
        status: IncidentStatus | None = None,
    ) -> list[IncidentRecord]:
        query = "SELECT * FROM sentinelgrid_incidents"
        parameters: list[Any] = []
        if status is not None:
            query += " WHERE status=?"
            parameters.append(IncidentStatus(status).value)
        query += " ORDER BY last_seen_at DESC LIMIT ?"
        parameters.append(self._limit(limit, 500))
        with self._lock, self._database() as db:
            rows = db.execute(query, parameters).fetchall()
        return [self._incident(row) for row in rows]

    def propose_action(
        self,
        *,
        asset_id: str,
        action_type: str,
        reason: str,
        requested_by: str,
    ) -> ActionProposal:
        action_type = action_type.strip().lower()
        if action_type not in self.ALLOWED_ACTIONS:
            raise StateConflictError(f"Unsupported SentinelGrid action: {action_type or '<blank>'}")
        with self._lock, self._database() as db:
            asset = self._require_asset(db, asset_id)
            self._validate_action(asset, action_type)
            software_only = action_type in self.SOFTWARE_ONLY_ACTIONS
            action = ActionProposal(
                action_id=f"action-{uuid4().hex[:16]}",
                asset_id=asset_id,
                action_type=action_type,
                reason=self._required_text(reason, "Action reason", 3),
                requested_by=self._required_text(requested_by, "Action requester", 2),
                risk=(
                    RiskLevel.LOW
                    if software_only
                    else (
                        RiskLevel.CRITICAL
                        if action_type == "emergency_shutdown"
                        else RiskLevel.ELEVATED
                    )
                ),
                status=(ActionStatus.APPROVED if software_only else ActionStatus.PENDING_APPROVAL),
                software_only=software_only,
                execution_allowed=False,
                created_at=self._now(),
            )
            db.execute(
                """INSERT INTO sentinelgrid_actions
                   (id,asset_id,action_type,reason,requested_by,risk,status,
                    software_only,execution_allowed,created_at,decision_note)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    action.action_id,
                    action.asset_id,
                    action.action_type,
                    action.reason,
                    action.requested_by,
                    action.risk.value,
                    action.status.value,
                    int(action.software_only),
                    0,
                    self._iso(action.created_at),
                    "",
                ),
            )
        return action

    def approve_action(
        self, action_id: str, *, decided_by: str, decision_note: str = ""
    ) -> ActionProposal:
        return self._decide(action_id, ActionStatus.APPROVED, decided_by, decision_note)

    def reject_action(
        self, action_id: str, *, decided_by: str, decision_note: str = ""
    ) -> ActionProposal:
        return self._decide(action_id, ActionStatus.REJECTED, decided_by, decision_note)

    def list_actions(self, *, limit: int = 100) -> list[ActionProposal]:
        with self._lock, self._database() as db:
            rows = db.execute(
                "SELECT * FROM sentinelgrid_actions ORDER BY created_at DESC LIMIT ?",
                (self._limit(limit, 500),),
            ).fetchall()
        return [self._action(row) for row in rows]

    def _decide(
        self,
        action_id: str,
        status: ActionStatus,
        decided_by: str,
        decision_note: str,
    ) -> ActionProposal:
        actor = self._required_text(decided_by, "Decision actor", 2)
        with self._lock, self._database() as db:
            current = self._require_action(db, action_id)
            if current.status != ActionStatus.PENDING_APPROVAL:
                raise StateConflictError(
                    f"Action {action_id} cannot be decided from {current.status.value}"
                )
            cursor = db.execute(
                """UPDATE sentinelgrid_actions
                   SET status=?,decided_at=?,decided_by=?,decision_note=?,
                       execution_allowed=0
                   WHERE id=? AND status='pending_approval'""",
                (
                    status.value,
                    self._iso(self._now()),
                    actor,
                    decision_note.strip(),
                    action_id,
                ),
            )
            if cursor.rowcount != 1:
                raise StateConflictError(f"Action {action_id} was already decided")
            return self._require_action(db, action_id)

    def _upsert_incident(
        self,
        db: sqlite3.Connection,
        asset_id: str,
        finding: _Finding,
        seen_at: datetime,
    ) -> IncidentRecord:
        row = db.execute(
            """SELECT * FROM sentinelgrid_incidents
               WHERE asset_id=? AND code=? AND status='open'""",
            (asset_id, finding.code),
        ).fetchone()
        if row:
            db.execute(
                """UPDATE sentinelgrid_incidents
                   SET risk=?,message=?,recommended_action=?,
                       occurrence_count=occurrence_count+1,last_seen_at=?
                   WHERE id=?""",
                (
                    finding.risk.value,
                    finding.message,
                    finding.recommended_action,
                    self._iso(seen_at),
                    row["id"],
                ),
            )
            row = db.execute(
                "SELECT * FROM sentinelgrid_incidents WHERE id=?", (row["id"],)
            ).fetchone()
            return self._incident(row)
        incident_id = f"incident-{uuid4().hex[:16]}"
        db.execute(
            """INSERT INTO sentinelgrid_incidents
               (id,asset_id,code,risk,status,message,recommended_action,
                occurrence_count,created_at,last_seen_at)
               VALUES (?,?,?,?,'open',?,?,1,?,?)""",
            (
                incident_id,
                asset_id,
                finding.code,
                finding.risk.value,
                finding.message,
                finding.recommended_action,
                self._iso(seen_at),
                self._iso(seen_at),
            ),
        )
        row = db.execute(
            "SELECT * FROM sentinelgrid_incidents WHERE id=?", (incident_id,)
        ).fetchone()
        return self._incident(row)

    def _diagnose(self, metrics: dict[str, MetricValue]) -> tuple[list[_Finding], set[str]]:
        findings: list[_Finding] = []
        evaluated: set[str] = set()
        numeric_checks = (
            (
                "methane_ppm",
                "methane_threshold_exceeded",
                RiskLevel.CRITICAL,
                1000,
                lambda value, threshold: value >= threshold,
                "Methane reading reached {value:g} ppm.",
                "request_maintenance",
            ),
            (
                "battery_temperature_c",
                "battery_temperature_high",
                RiskLevel.CRITICAL,
                60,
                lambda value, threshold: value >= threshold,
                "Battery temperature reached {value:g} C.",
                "emergency_shutdown",
            ),
            (
                "battery_percent",
                "battery_charge_low",
                RiskLevel.ELEVATED,
                10,
                lambda value, threshold: value <= threshold,
                "Battery charge fell to {value:g} percent.",
                "schedule_charge",
            ),
        )
        for metric, code, risk, threshold, unsafe, message, recommendation in numeric_checks:
            if metric not in metrics:
                continue
            evaluated.add(code)
            value = self._number(metrics[metric], metric)
            if unsafe(value, threshold):
                findings.append(_Finding(code, risk, message.format(value=value), recommendation))
        boolean_checks = (
            (
                "link_online",
                False,
                "control_link_offline",
                RiskLevel.ELEVATED,
                "The asset stopped reporting an online control link.",
                "inspect",
            ),
            (
                "charger_fault",
                True,
                "charging_station_fault",
                RiskLevel.CRITICAL,
                "A charging-system fault was reported.",
                "request_maintenance",
            ),
        )
        for metric, unsafe_value, code, risk, message, recommendation in boolean_checks:
            if metric not in metrics:
                continue
            evaluated.add(code)
            if self._boolean(metrics[metric], metric) is unsafe_value:
                findings.append(_Finding(code, risk, message, recommendation))
        return findings, evaluated

    def _validate_action(self, asset: AssetRecord, action_type: str) -> None:
        if action_type in self.SOFTWARE_ONLY_ACTIONS:
            return
        aliases = {action_type, f"action:{action_type}", f"supports:{action_type}"}
        if asset.asset_type in self.ACTION_ASSET_TYPES[action_type] or aliases.intersection(
            asset.capabilities
        ):
            return
        raise StateConflictError(
            f"Action {action_type} is not supported by {asset.asset_type.value} "
            f"asset {asset.asset_id}"
        )

    def _require_asset(self, db: sqlite3.Connection, asset_id: str) -> AssetRecord:
        row = db.execute("SELECT * FROM sentinelgrid_assets WHERE id=?", (asset_id,)).fetchone()
        if row is None:
            raise AssetNotFoundError(f"Unknown SentinelGrid asset: {asset_id}")
        return self._asset(row)

    def _require_action(self, db: sqlite3.Connection, action_id: str) -> ActionProposal:
        row = db.execute("SELECT * FROM sentinelgrid_actions WHERE id=?", (action_id,)).fetchone()
        if row is None:
            raise ActionNotFoundError(f"Unknown SentinelGrid action: {action_id}")
        return self._action(row)

    @staticmethod
    def _number(value: object, metric: str) -> float:
        if isinstance(value, bool):
            raise InvalidInputError(f"Metric {metric} must be numeric")
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise InvalidInputError(f"Metric {metric} must be numeric") from exc
        if not math.isfinite(number):
            raise InvalidInputError(f"Metric {metric} must be finite")
        return number

    @staticmethod
    def _boolean(value: object, metric: str) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "1", "yes"}:
                return True
            if normalized in {"false", "0", "no"}:
                return False
        raise InvalidInputError(f"Metric {metric} must be boolean")

    @staticmethod
    def _required_text(value: str, label: str, minimum: int) -> str:
        normalized = value.strip()
        if len(normalized) < minimum:
            raise InvalidInputError(
                f"{label} must contain at least {minimum} non-whitespace characters"
            )
        return normalized

    @staticmethod
    def _limit(value: int, maximum: int) -> int:
        if value < 1 or value > maximum:
            raise InvalidInputError(f"Limit must be between 1 and {maximum}")
        return value

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _aware(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @classmethod
    def _iso(cls, value: datetime) -> str:
        return cls._aware(value).isoformat()

    @staticmethod
    def _date(value: str | None) -> datetime | None:
        if value is None:
            return None
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _count(db: sqlite3.Connection, table: str, where: str | None = None) -> int:
        query = f"SELECT COUNT(*) FROM {table}"
        if where:
            query += f" WHERE {where}"
        return int(db.execute(query).fetchone()[0])

    def _asset(self, row: sqlite3.Row) -> AssetRecord:
        return AssetRecord(
            row["id"],
            row["name"],
            AssetType(row["asset_type"]),
            row["site"],
            tuple(json.loads(row["capabilities_json"] or "[]")),
            self._date(row["registered_at"]),
        )

    def _incident(self, row: sqlite3.Row) -> IncidentRecord:
        return IncidentRecord(
            row["id"],
            row["asset_id"],
            row["code"],
            RiskLevel(row["risk"]),
            IncidentStatus(row["status"]),
            row["message"],
            row["recommended_action"],
            int(row["occurrence_count"]),
            self._date(row["created_at"]),
            self._date(row["last_seen_at"]),
            self._date(row["resolved_at"]),
        )

    def _action(self, row: sqlite3.Row) -> ActionProposal:
        return ActionProposal(
            row["id"],
            row["asset_id"],
            row["action_type"],
            row["reason"],
            row["requested_by"],
            RiskLevel(row["risk"]),
            ActionStatus(row["status"]),
            bool(row["software_only"]),
            bool(row["execution_allowed"]),
            self._date(row["created_at"]),
            self._date(row["decided_at"]),
            row["decided_by"],
            row["decision_note"] or "",
        )

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
    """Persist and supervise industrial assets without commanding physical hardware."""

    SOFTWARE_ONLY_ACTIONS = frozenset(
        {
            "analyze_telemetry",
            "inspect",
            "simulate",
        }
    )
    CONTROLLED_ACTIONS = frozenset(
        {
            "emergency_shutdown",
            "move",
            "request_maintenance",
            "schedule_charge",
        }
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
    INCIDENT_LIMIT = 500
    TELEMETRY_LIMIT = 5000

    def __init__(self, connection_factory: ConnectionFactory | None = None) -> None:
        self._lock = RLock()
        self._connection_factory = connection_factory or self._default_connection
        self.ensure_schema()

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _default_connection() -> sqlite3.Connection:
        configured = os.getenv("SENTINELGRID_DB_PATH") or os.getenv(
            "AUTH_DB_PATH", "data/auth.db"
        )
        path = Path(configured)
        path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(path)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
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
        """Create the durable SentinelGrid schema without replacing existing data."""

        with self._lock, self._database() as db:
            db.executescript(
                """
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
                    ON sentinelgrid_incidents(asset_id, code)
                    WHERE status='open';
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
                """
            )

    def reset(self) -> None:
        """Delete SentinelGrid records. Intended for isolated tests only."""

        self.ensure_schema()
        with self._lock, self._database() as db:
            db.execute("DELETE FROM sentinelgrid_actions")
            db.execute("DELETE FROM sentinelgrid_telemetry")
            db.execute("DELETE FROM sentinelgrid_incidents")
            db.execute("DELETE FROM sentinelgrid_assets")

    def status(self) -> dict[str, Any]:
        with self._lock, self._database() as db:
            counts = {
                "assets": self._count(db, "sentinelgrid_assets"),
                "telemetry_records": self._count(db, "sentinelgrid_telemetry"),
                "open_incidents": self._count(
                    db, "sentinelgrid_incidents", "status='open'"
                ),
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
        normalized_name = self._required_text(name, "Asset name", minimum=2)
        normalized_site = self._required_text(site, "Asset site", minimum=2)
        normalized_type = AssetType(asset_type)
        normalized_capabilities = tuple(
            sorted({item.strip().lower() for item in capabilities if item.strip()})
        )
        asset = AssetRecord(
            asset_id=f"asset-{uuid4().hex[:16]}",
            name=normalized_name,
            asset_type=normalized_type,
            site=normalized_site,
            capabilities=normalized_capabilities,
            registered_at=self._now(),
        )
        with self._lock, self._database() as db:
            db.execute(
                """
                INSERT INTO sentinelgrid_assets(
                    id,name,asset_type,site,capabilities_json,registered_at
                ) VALUES (?,?,?,?,?,?)
                """,
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
        normalized_limit = self._bounded_limit(limit, maximum=500)
        with self._lock, self._database() as db:
            rows = db.execute(
                """
                SELECT * FROM sentinelgrid_assets
                ORDER BY registered_at ASC LIMIT ?
                """,
                (normalized_limit,),
            ).fetchall()
        return [self._asset_from_row(row) for row in rows]

    def record_telemetry(
        self,
        *,
        asset_id: str,
        metrics: dict[str, MetricValue],
        observed_at: datetime | None = None,
    ) -> tuple[TelemetryRecord, list[IncidentRecord]]:
        if not metrics:
            raise InvalidInputError("Telemetry metrics cannot be empty")
        normalized_metrics = dict(metrics)
        findings, evaluated_codes = self._diagnose(normalized_metrics)
        received_at = self._now()
        normalized_observed_at = self._aware_datetime(observed_at or received_at)

        with self._lock, self._database() as db:
            self._require_asset(db, asset_id)
            active_incidents = [
                self._upsert_incident(db, asset_id, finding, received_at)
                for finding in findings
            ]
            active_codes = {item.code for item in active_incidents}
            resolved_codes = evaluated_codes - active_codes
            if resolved_codes:
                placeholders = ",".join("?" for _ in resolved_codes)
                db.execute(
                    f"""
                    UPDATE sentinelgrid_incidents
                    SET status='resolved', resolved_at=?
                    WHERE asset_id=? AND status='open'
                      AND code IN ({placeholders})
                    """,
                    (
                        self._iso(received_at),
                        asset_id,
                        *sorted(resolved_codes),
                    ),
                )

            telemetry = TelemetryRecord(
                telemetry_id=f"telemetry-{uuid4().hex[:16]}",
                asset_id=asset_id,
                metrics=normalized_metrics,
                observed_at=normalized_observed_at,
                received_at=received_at,
                incident_ids=tuple(item.incident_id for item in active_incidents),
            )
            db.execute(
                """
                INSERT INTO sentinelgrid_telemetry(
                    id,asset_id,metrics_json,observed_at,received_at,incident_ids_json
                ) VALUES (?,?,?,?,?,?)
                """,
                (
                    telemetry.telemetry_id,
                    telemetry.asset_id,
                    json.dumps(telemetry.metrics, sort_keys=True),
                    self._iso(telemetry.observed_at),
                    self._iso(telemetry.received_at),
                    json.dumps(telemetry.incident_ids),
                ),
            )
            self._trim_telemetry(db)
        return telemetry, active_incidents

    def list_incidents(
        self,
        *,
        limit: int = 100,
        status: IncidentStatus | None = None,
    ) -> list[IncidentRecord]:
        normalized_limit = self._bounded_limit(limit, maximum=self.INCIDENT_LIMIT)
        query = "SELECT * FROM sentinelgrid_incidents"
        parameters: list[Any] = []
        if status is not None:
            query += " WHERE status=?"
            parameters.append(IncidentStatus(status).value)
        query += " ORDER BY last_seen_at DESC LIMIT ?"
        parameters.append(normalized_limit)
        with self._lock, self._database() as db:
            rows = db.execute(query, parameters).fetchall()
        return [self._incident_from_row(row) for row in rows]

    def propose_action(
        self,
        *,
        asset_id: str,
        action_type: str,
        reason: str,
        requested_by: str,
    ) -> ActionProposal:
        normalized_action = action_type.strip().lower()
        if normalized_action not in self.ALLOWED_ACTIONS:
            raise StateConflictError(
                f"Unsupported SentinelGrid action: {normalized_action or '<blank>'}"
            )
        normalized_reason = self._required_text(reason, "Action reason", minimum=3)
        normalized_requester = self._required_text(
            requested_by, "Action requester", minimum=2
        )

        with self._lock, self._database() as db:
            asset = self._require_asset(db, asset_id)
            self._validate_action_for_asset(asset, normalized_action)
            software_only = normalized_action in self.SOFTWARE_ONLY_ACTIONS
            proposal = ActionProposal(
                action_id=f"action-{uuid4().hex[:16]}",
                asset_id=asset_id,
                action_type=normalized_action,
                reason=normalized_reason,
                requested_by=normalized_requester,
                risk=(
                    RiskLevel.LOW
                    if software_only
                    else RiskLevel.CRITICAL
                    if normalized_action == "emergency_shutdown"
                    else RiskLevel.ELEVATED
                ),
                status=(
                    ActionStatus.APPROVED
                    if software_only
                    else ActionStatus.PENDING_APPROVAL
                ),
                software_only=software_only,
                execution_allowed=False,
                created_at=self._now(),
            )
            self._insert_action(db, proposal)
        return proposal

    def approve_action(
        self,
        action_id: str,
        *,
        decided_by: str,
        decision_note: str = "",
    ) -> ActionProposal:
        return self._decide_action(
            action_id,
            status=ActionStatus.APPROVED,
            decided_by=decided_by,
            decision_note=decision_note,
        )

    def reject_action(
        self,
        action_id: str,
        *,
        decided_by: str,
        decision_note: str = "",
    ) -> ActionProposal:
        return self._decide_action(
            action_id,
            status=ActionStatus.REJECTED,
            decided_by=decided_by,
            decision_note=decision_note,
        )

    def list_actions(self, *, limit: int = 100) -> list[ActionProposal]:
        normalized_limit = self._bounded_limit(limit, maximum=500)
        with self._lock, self._database() as db:
            rows = db.execute(
                """
                SELECT * FROM sentinelgrid_actions
                ORDER BY created_at DESC LIMIT ?
                """,
                (normalized_limit,),
            ).fetchall()
        return [self._action_from_row(row) for row in rows]

    def _decide_action(
        self,
        action_id: str,
        *,
        status: ActionStatus,
        decided_by: str,
        decision_note: str,
    ) -> ActionProposal:
        normalized_actor = self._required_text(decided_by, "Decision actor", minimum=2)
        normalized_note = decision_note.strip()
        decided_at = self._now()
        with self._lock, self._database() as db:
            current = self._require_action(db, action_id)
            if current.status != ActionStatus.PENDING_APPROVAL:
                raise StateConflictError(
                    f"Action {action_id} cannot be decided from {current.status.value}"
                )
            db.execute(
                """
                UPDATE sentinelgrid_actions
                SET status=?, decided_at=?, decided_by=?, decision_note=?,
                    execution_allowed=0
                WHERE id=? AND status='pending_approval'
                """,
                (
                    status.value,
                    self._iso(decided_at),
                    normalized_actor,
                    normalized_note,
                    action_id,
                ),
            )
            updated = self._require_action(db, action_id)
        return updated

    def _upsert_incident(
        self,
        db: sqlite3.Connection,
        asset_id: str,
        finding: _Finding,
        seen_at: datetime,
    ) -> IncidentRecord:
        existing = db.execute(
            """
            SELECT * FROM sentinelgrid_incidents
            WHERE asset_id=? AND code=? AND status='open'
            """,
            (asset_id, finding.code),
        ).fetchone()
        if existing:
            db.execute(
                """
                UPDATE sentinelgrid_incidents
                SET risk=?, message=?, recommended_action=?,
                    occurrence_count=occurrence_count+1, last_seen_at=?
                WHERE id=?
                """,
                (
                    finding.risk.value,
                    finding.message,
                    finding.recommended_action,
                    self._iso(seen_at),
                    existing["id"],
                ),
            )
            row = db.execute(
                "SELECT * FROM sentinelgrid_incidents WHERE id=?",
                (existing["id"],),
            ).fetchone()
            return self._incident_from_row(row)

        incident_id = f"incident-{uuid4().hex[:16]}"
        db.execute(
            """
            INSERT INTO sentinelgrid_incidents(
                id,asset_id,code,risk,status,message,recommended_action,
                occurrence_count,created_at,last_seen_at,resolved_at
            ) VALUES (?,?,?,?,'open',?,?,1,?,?,NULL)
            """,
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
        return self._incident_from_row(row)

    def _diagnose(
        self,
        metrics: dict[str, MetricValue],
    ) -> tuple[list[_Finding], set[str]]:
        findings: list[_Finding] = []
        evaluated_codes: set[str] = set()

        if "methane_ppm" in metrics:
            evaluated_codes.add("methane_threshold_exceeded")
            methane_ppm = self._number(metrics["methane_ppm"], "methane_ppm")
            if methane_ppm >= 1000:
                findings.append(
                    _Finding(
                        "methane_threshold_exceeded",
                        RiskLevel.CRITICAL,
                        f"Methane reading reached {methane_ppm:g} ppm.",
                        "request_maintenance",
                    )
                )

        if "battery_temperature_c" in metrics:
            evaluated_codes.add("battery_temperature_high")
            battery_temperature = self._number(
                metrics["battery_temperature_c"], "battery_temperature_c"
            )
            if battery_temperature >= 60:
                findings.append(
                    _Finding(
                        "battery_temperature_high",
                        RiskLevel.CRITICAL,
                        f"Battery temperature reached {battery_temperature:g} C.",
                        "emergency_shutdown",
                    )
                )

        if "battery_percent" in metrics:
            evaluated_codes.add("battery_charge_low")
            battery_percent = self._number(metrics["battery_percent"], "battery_percent")
            if battery_percent <= 10:
                findings.append(
                    _Finding(
                        "battery_charge_low",
                        RiskLevel.ELEVATED,
                        f"Battery charge fell to {battery_percent:g} percent.",
                        "schedule_charge",
                    )
                )

        if "link_online" in metrics:
            evaluated_codes.add("control_link_offline")
            if self._boolean(metrics["link_online"], "link_online") is False:
                findings.append(
                    _Finding(
                        "control_link_offline",
                        RiskLevel.ELEVATED,
                        "The asset stopped reporting an online control link.",
                        "inspect",
                    )
                )

        if "charger_fault" in metrics:
            evaluated_codes.add("charging_station_fault")
            if self._boolean(metrics["charger_fault"], "charger_fault") is True:
                findings.append(
                    _Finding(
                        "charging_station_fault",
                        RiskLevel.CRITICAL,
                        "A charging-system fault was reported.",
                        "request_maintenance",
                    )
                )

        return findings, evaluated_codes

    def _validate_action_for_asset(self, asset: AssetRecord, action_type: str) -> None:
        if action_type in self.SOFTWARE_ONLY_ACTIONS:
            return
        allowed_types = self.ACTION_ASSET_TYPES[action_type]
        capability_aliases = {
            action_type,
            f"action:{action_type}",
            f"supports:{action_type}",
        }
        if asset.asset_type in allowed_types or capability_aliases.intersection(
            asset.capabilities
        ):
            return
        raise StateConflictError(
            f"Action {action_type} is not supported by {asset.asset_type.value} "
            f"asset {asset.asset_id}"
        )

    @staticmethod
    def _number(value: object, metric_name: str) -> float:
        if isinstance(value, bool):
            raise InvalidInputError(f"Metric {metric_name} must be numeric")
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise InvalidInputError(f"Metric {metric_name} must be numeric") from exc
        if not math.isfinite(number):
            raise InvalidInputError(f"Metric {metric_name} must be finite")
        return number

    @staticmethod
    def _boolean(value: object, metric_name: str) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "1", "yes"}:
                return True
            if normalized in {"false", "0", "no"}:
                return False
        raise InvalidInputError(f"Metric {metric_name} must be boolean")

    @staticmethod
    def _required_text(value: str, label: str, *, minimum: int) -> str:
        normalized = value.strip()
        if len(normalized) < minimum:
            raise InvalidInputError(
                f"{label} must contain at least {minimum} non-whitespace characters"
            )
        return normalized

    @staticmethod
    def _bounded_limit(value: int, *, maximum: int) -> int:
        if value < 1 or value > maximum:
            raise InvalidInputError(f"Limit must be between 1 and {maximum}")
        return value

    @staticmethod
    def _aware_datetime(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @classmethod
    def _iso(cls, value: datetime) -> str:
        return cls._aware_datetime(value).isoformat()

    @staticmethod
    def _datetime(value: str | None) -> datetime | None:
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

    def _require_asset(self, db: sqlite3.Connection, asset_id: str) -> AssetRecord:
        row = db.execute(
            "SELECT * FROM sentinelgrid_assets WHERE id=?", (asset_id,)
        ).fetchone()
        if row is None:
            raise AssetNotFoundError(f"Unknown SentinelGrid asset: {asset_id}")
        return self._asset_from_row(row)

    def _require_action(self, db: sqlite3.Connection, action_id: str) -> ActionProposal:
        row = db.execute(
            "SELECT * FROM sentinelgrid_actions WHERE id=?", (action_id,)
        ).fetchone()
        if row is None:
            raise ActionNotFoundError(f"Unknown SentinelGrid action: {action_id}")
        return self._action_from_row(row)

    @staticmethod
    def _insert_action(db: sqlite3.Connection, action: ActionProposal) -> None:
        db.execute(
            """
            INSERT INTO sentinelgrid_actions(
                id,asset_id,action_type,reason,requested_by,risk,status,
                software_only,execution_allowed,created_at,decided_at,
                decided_by,decision_note
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                action.action_id,
                action.asset_id,
                action.action_type,
                action.reason,
                action.requested_by,
                action.risk.value,
                action.status.value,
                int(action.software_only),
                int(action.execution_allowed),
                SentinelGridControlPlane._iso(action.created_at),
                None,
                None,
                action.decision_note,
            ),
        )

    def _trim_telemetry(self, db: sqlite3.Connection) -> None:
        db.execute(
            """
            DELETE FROM sentinelgrid_telemetry
            WHERE id IN (
                SELECT id FROM sentinelgrid_telemetry
                ORDER BY received_at DESC
                LIMIT -1 OFFSET ?
            )
            """,
            (self.TELEMETRY_LIMIT,),
        )

    def _asset_from_row(self, row: sqlite3.Row) -> AssetRecord:
        return AssetRecord(
            asset_id=row["id"],
            name=row["name"],
            asset_type=AssetType(row["asset_type"]),
            site=row["site"],
            capabilities=tuple(json.loads(row["capabilities_json"] or "[]")),
            registered_at=self._datetime(row["registered_at"]),
        )

    def _incident_from_row(self, row: sqlite3.Row) -> IncidentRecord:
        return IncidentRecord(
            incident_id=row["id"],
            asset_id=row["asset_id"],
            code=row["code"],
            risk=RiskLevel(row["risk"]),
            status=IncidentStatus(row["status"]),
            message=row["message"],
            recommended_action=row["recommended_action"],
            occurrence_count=int(row["occurrence_count"]),
            created_at=self._datetime(row["created_at"]),
            last_seen_at=self._datetime(row["last_seen_at"]),
            resolved_at=self._datetime(row["resolved_at"]),
        )

    def _action_from_row(self, row: sqlite3.Row) -> ActionProposal:
        return ActionProposal(
            action_id=row["id"],
            asset_id=row["asset_id"],
            action_type=row["action_type"],
            reason=row["reason"],
            requested_by=row["requested_by"],
            risk=RiskLevel(row["risk"]),
            status=ActionStatus(row["status"]),
            software_only=bool(row["software_only"]),
            execution_allowed=bool(row["execution_allowed"]),
            created_at=self._datetime(row["created_at"]),
            decided_at=self._datetime(row["decided_at"]),
            decided_by=row["decided_by"],
            decision_note=row["decision_note"] or "",
        )

"""Safety-first industrial autonomy control plane for Amosclaud SentinelGrid."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from threading import RLock
from typing import Any
from uuid import uuid4


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


class ActionStatus(str, Enum):
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"


class SentinelGridError(RuntimeError):
    """Base error for invalid SentinelGrid operations."""


class AssetNotFoundError(SentinelGridError):
    """Raised when an asset identifier is unknown."""


class ActionNotFoundError(SentinelGridError):
    """Raised when an action proposal identifier is unknown."""


class StateConflictError(SentinelGridError):
    """Raised when a requested transition is not allowed."""


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
    message: str
    recommended_action: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class TelemetryRecord:
    telemetry_id: str
    asset_id: str
    metrics: dict[str, float | int | bool | str]
    observed_at: datetime
    received_at: datetime
    incident_ids: tuple[str, ...]


@dataclass(slots=True)
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


class SentinelGridControlPlane:
    """Coordinate autonomous assets without directly commanding physical hardware."""

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

    def __init__(self) -> None:
        self._lock = RLock()
        self._assets: dict[str, AssetRecord] = {}
        self._telemetry: list[TelemetryRecord] = []
        self._incidents: dict[str, IncidentRecord] = {}
        self._actions: dict[str, ActionProposal] = {}

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    def reset(self) -> None:
        """Clear volatile state. Intended for tests and isolated development only."""

        with self._lock:
            self._assets.clear()
            self._telemetry.clear()
            self._incidents.clear()
            self._actions.clear()

    def status(self) -> dict[str, Any]:
        with self._lock:
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
                "assets": len(self._assets),
                "telemetry_records": len(self._telemetry),
                "open_incidents": len(self._incidents),
                "action_proposals": len(self._actions),
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
            name=name.strip(),
            asset_type=asset_type,
            site=site.strip(),
            capabilities=tuple(
                sorted({item.strip() for item in capabilities if item.strip()})
            ),
            registered_at=self._now(),
        )
        with self._lock:
            self._assets[asset.asset_id] = asset
        return asset

    def list_assets(self) -> list[AssetRecord]:
        with self._lock:
            return sorted(self._assets.values(), key=lambda item: item.registered_at)

    def record_telemetry(
        self,
        *,
        asset_id: str,
        metrics: dict[str, float | int | bool | str],
        observed_at: datetime | None = None,
    ) -> tuple[TelemetryRecord, list[IncidentRecord]]:
        with self._lock:
            self._require_asset(asset_id)
            incidents = self._diagnose(asset_id, metrics)
            for incident in incidents:
                self._incidents[incident.incident_id] = incident
            telemetry = TelemetryRecord(
                telemetry_id=f"telemetry-{uuid4().hex[:16]}",
                asset_id=asset_id,
                metrics=dict(metrics),
                observed_at=observed_at or self._now(),
                received_at=self._now(),
                incident_ids=tuple(item.incident_id for item in incidents),
            )
            self._telemetry.append(telemetry)
            self._telemetry = self._telemetry[-500:]
            return telemetry, incidents

    def list_incidents(self) -> list[IncidentRecord]:
        with self._lock:
            return sorted(
                self._incidents.values(),
                key=lambda item: item.created_at,
                reverse=True,
            )

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
                f"Unsupported SentinelGrid action: {normalized_action}"
            )

        with self._lock:
            self._require_asset(asset_id)
            software_only = normalized_action in self.SOFTWARE_ONLY_ACTIONS
            proposal = ActionProposal(
                action_id=f"action-{uuid4().hex[:16]}",
                asset_id=asset_id,
                action_type=normalized_action,
                reason=reason.strip(),
                requested_by=requested_by.strip(),
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
            self._actions[proposal.action_id] = proposal
            return proposal

    def approve_action(
        self,
        action_id: str,
        *,
        decided_by: str,
        decision_note: str = "",
    ) -> ActionProposal:
        with self._lock:
            action = self._require_action(action_id)
            if action.status != ActionStatus.PENDING_APPROVAL:
                raise StateConflictError(
                    f"Action {action_id} cannot be approved from {action.status.value}"
                )
            action.status = ActionStatus.APPROVED
            action.decided_at = self._now()
            action.decided_by = decided_by.strip()
            action.decision_note = decision_note.strip()
            action.execution_allowed = False
            return action

    def reject_action(
        self,
        action_id: str,
        *,
        decided_by: str,
        decision_note: str = "",
    ) -> ActionProposal:
        with self._lock:
            action = self._require_action(action_id)
            if action.status != ActionStatus.PENDING_APPROVAL:
                raise StateConflictError(
                    f"Action {action_id} cannot be rejected from {action.status.value}"
                )
            action.status = ActionStatus.REJECTED
            action.decided_at = self._now()
            action.decided_by = decided_by.strip()
            action.decision_note = decision_note.strip()
            action.execution_allowed = False
            return action

    def list_actions(self) -> list[ActionProposal]:
        with self._lock:
            return sorted(
                self._actions.values(),
                key=lambda item: item.created_at,
                reverse=True,
            )

    def _require_asset(self, asset_id: str) -> AssetRecord:
        asset = self._assets.get(asset_id)
        if asset is None:
            raise AssetNotFoundError(f"Unknown SentinelGrid asset: {asset_id}")
        return asset

    def _require_action(self, action_id: str) -> ActionProposal:
        action = self._actions.get(action_id)
        if action is None:
            raise ActionNotFoundError(f"Unknown SentinelGrid action: {action_id}")
        return action

    def _diagnose(
        self,
        asset_id: str,
        metrics: dict[str, float | int | bool | str],
    ) -> list[IncidentRecord]:
        findings: list[tuple[str, RiskLevel, str, str]] = []
        methane_ppm = self._number(metrics.get("methane_ppm"))
        battery_temperature = self._number(metrics.get("battery_temperature_c"))
        battery_percent = self._number(metrics.get("battery_percent"))

        if methane_ppm is not None and methane_ppm >= 1000:
            findings.append(
                (
                    "methane_threshold_exceeded",
                    RiskLevel.CRITICAL,
                    f"Methane reading reached {methane_ppm:g} ppm.",
                    "request_maintenance",
                )
            )
        if battery_temperature is not None and battery_temperature >= 60:
            findings.append(
                (
                    "battery_temperature_high",
                    RiskLevel.CRITICAL,
                    f"Battery temperature reached {battery_temperature:g} C.",
                    "emergency_shutdown",
                )
            )
        if battery_percent is not None and battery_percent <= 10:
            findings.append(
                (
                    "battery_charge_low",
                    RiskLevel.ELEVATED,
                    f"Battery charge fell to {battery_percent:g} percent.",
                    "schedule_charge",
                )
            )
        if metrics.get("link_online") is False:
            findings.append(
                (
                    "control_link_offline",
                    RiskLevel.ELEVATED,
                    "The asset stopped reporting an online control link.",
                    "inspect",
                )
            )
        if metrics.get("charger_fault") is True:
            findings.append(
                (
                    "charging_station_fault",
                    RiskLevel.CRITICAL,
                    "A charging-system fault was reported.",
                    "request_maintenance",
                )
            )

        now = self._now()
        return [
            IncidentRecord(
                incident_id=f"incident-{uuid4().hex[:16]}",
                asset_id=asset_id,
                code=code,
                risk=risk,
                message=message,
                recommended_action=recommended_action,
                created_at=now,
            )
            for code, risk, message, recommended_action in findings
        ]

    @staticmethod
    def _number(value: object) -> float | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        return None

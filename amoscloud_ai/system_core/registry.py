"""Central inventory, doctor allocation, and policy contracts for Amosclaud.

The core owns the exact component counts requested by the platform owner.  It
materializes independent doctor lanes, component policy slots, a complete
inventory coverage check, and a single-core execution gate.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from threading import Lock
from typing import Iterable, Iterator, Mapping

DOCTOR_COUNTS: dict[str, int] = {
    "amosclaud-clean": 1,
    "amosclaud-fixer": 2,
    "amosclaud-action": 3,
    "amosclaud-autonomous": 4,
    "amosclaud-security": 3,
    "amosclaud-codex-agent": 10,
}

POLICY_COUNTS: dict[str, int] = {
    "amosclaud-fixer": 12,
    "amosclaud-action": 11,
    "amosclaud-autonomous": 25,
    "amosclaud-ai-agent": 13,
    "amosclaud-api-key": 50,
}

EXPECTED_DOCTOR_TOTAL = 23
EXPECTED_POLICY_TOTAL = 111


class SystemCoreError(RuntimeError):
    """Base error for invalid or unavailable system-core state."""


class ManifestError(SystemCoreError):
    """Raised when doctor, policy, CPU, or inventory contracts are invalid."""


class CoreBusyError(SystemCoreError):
    """Raised when the single execution lane is already occupied."""


class DoctorUnavailableError(SystemCoreError):
    """Raised when no healthy doctor exists for a component."""


@dataclass(frozen=True, slots=True)
class CpuPolicy:
    """One-core policy.

    ``utilization_ceiling_percent`` is a maximum budget, not a request to keep
    a processor continuously saturated.
    """

    logical_cores: int = 1
    max_parallel_doctors: int = 1
    utilization_ceiling_percent: int = 100

    def validate(self) -> None:
        if self.logical_cores != 1:
            raise ManifestError("Amosclaud System Core must use exactly one logical CPU core")
        if self.max_parallel_doctors != 1:
            raise ManifestError("Only one doctor lane may execute at a time")
        if self.utilization_ceiling_percent != 100:
            raise ManifestError("The single-core utilization ceiling must be 100 percent")


@dataclass(slots=True)
class DoctorLane:
    doctor_id: str
    component: str
    ordinal: int
    healthy: bool = True
    failures: int = 0


@dataclass(frozen=True, slots=True)
class PolicySlot:
    policy_id: str
    component: str
    ordinal: int


@dataclass(slots=True)
class InventoryManifest:
    """Tracks whether every required file, requirement, and tool is accounted for."""

    required_requirements: set[str] = field(default_factory=set)
    required_files: set[str] = field(default_factory=set)
    required_tools: set[str] = field(default_factory=set)
    discovered_requirements: set[str] = field(default_factory=set)
    discovered_files: set[str] = field(default_factory=set)
    discovered_tools: set[str] = field(default_factory=set)

    @staticmethod
    def _normalize(values: Iterable[str]) -> set[str]:
        return {str(value).strip() for value in values if str(value).strip()}

    @classmethod
    def expected(
        cls,
        *,
        requirements: Iterable[str] = (),
        files: Iterable[str] = (),
        tools: Iterable[str] = (),
    ) -> "InventoryManifest":
        return cls(
            required_requirements=cls._normalize(requirements),
            required_files=cls._normalize(files),
            required_tools=cls._normalize(tools),
        )

    def record(
        self,
        *,
        requirements: Iterable[str] = (),
        files: Iterable[str] = (),
        tools: Iterable[str] = (),
    ) -> None:
        self.discovered_requirements.update(self._normalize(requirements))
        self.discovered_files.update(self._normalize(files))
        self.discovered_tools.update(self._normalize(tools))

    def missing(self) -> dict[str, tuple[str, ...]]:
        return {
            "requirements": tuple(
                sorted(self.required_requirements - self.discovered_requirements)
            ),
            "files": tuple(sorted(self.required_files - self.discovered_files)),
            "tools": tuple(sorted(self.required_tools - self.discovered_tools)),
        }

    @property
    def coverage_percent(self) -> int:
        expected = len(self.required_requirements) + len(self.required_files) + len(self.required_tools)
        if expected == 0:
            return 100
        missing = sum(len(values) for values in self.missing().values())
        return round(((expected - missing) / expected) * 100)

    def assert_complete(self) -> None:
        missing = self.missing()
        if any(missing.values()):
            raise ManifestError(f"System inventory is incomplete: {missing}")


@dataclass(frozen=True, slots=True)
class CoverageReport:
    doctor_total: int
    policy_total: int
    doctor_components: int
    policy_components: int
    system_policy_coverage_percent: int
    inventory_coverage_percent: int
    cpu_logical_cores: int
    active_lane_limit: int


class AmosclaudSystemCore:
    """Immutable topology plus a bounded single-core doctor scheduler."""

    def __init__(
        self,
        *,
        doctor_counts: Mapping[str, int] | None = None,
        policy_counts: Mapping[str, int] | None = None,
        cpu_policy: CpuPolicy | None = None,
        inventory: InventoryManifest | None = None,
    ) -> None:
        self.doctor_counts = dict(doctor_counts or DOCTOR_COUNTS)
        self.policy_counts = dict(policy_counts or POLICY_COUNTS)
        self.cpu_policy = cpu_policy or CpuPolicy()
        self.inventory = inventory or InventoryManifest.expected()
        self._validate_exact_manifest()

        self.doctors = self._materialize_doctors()
        self.policies = self._materialize_policies()
        self._component_names = tuple(sorted(set(self.doctor_counts) | set(self.policy_counts)))
        self._system_policy_inheritance = {component: True for component in self._component_names}
        self._execution_lock = Lock()
        self._round_robin: dict[str, int] = {component: 0 for component in self.doctor_counts}

    def _validate_exact_manifest(self) -> None:
        if self.doctor_counts != DOCTOR_COUNTS:
            raise ManifestError(
                f"Doctor manifest must exactly match {DOCTOR_COUNTS}; got {self.doctor_counts}"
            )
        if self.policy_counts != POLICY_COUNTS:
            raise ManifestError(
                f"Policy manifest must exactly match {POLICY_COUNTS}; got {self.policy_counts}"
            )
        if sum(self.doctor_counts.values()) != EXPECTED_DOCTOR_TOTAL:
            raise ManifestError("Doctor manifest must materialize exactly 23 doctors")
        if sum(self.policy_counts.values()) != EXPECTED_POLICY_TOTAL:
            raise ManifestError("Policy manifest must materialize exactly 111 policies")
        if any(count <= 0 for count in self.doctor_counts.values()):
            raise ManifestError("Every registered doctor component needs at least one doctor")
        if any(count <= 0 for count in self.policy_counts.values()):
            raise ManifestError("Every registered policy component needs at least one policy")
        self.cpu_policy.validate()

    def _materialize_doctors(self) -> dict[str, list[DoctorLane]]:
        return {
            component: [
                DoctorLane(
                    doctor_id=f"{component}-doctor-{ordinal:02d}",
                    component=component,
                    ordinal=ordinal,
                )
                for ordinal in range(1, count + 1)
            ]
            for component, count in self.doctor_counts.items()
        }

    def _materialize_policies(self) -> dict[str, list[PolicySlot]]:
        return {
            component: [
                PolicySlot(
                    policy_id=f"{component}-policy-{ordinal:03d}",
                    component=component,
                    ordinal=ordinal,
                )
                for ordinal in range(1, count + 1)
            ]
            for component, count in self.policy_counts.items()
        }

    def validate(self) -> CoverageReport:
        self._validate_exact_manifest()
        doctor_ids = [doctor.doctor_id for lanes in self.doctors.values() for doctor in lanes]
        policy_ids = [policy.policy_id for slots in self.policies.values() for policy in slots]
        if len(doctor_ids) != len(set(doctor_ids)):
            raise ManifestError("Doctor IDs must be unique")
        if len(policy_ids) != len(set(policy_ids)):
            raise ManifestError("Policy IDs must be unique")
        if len(doctor_ids) != EXPECTED_DOCTOR_TOTAL:
            raise ManifestError("Materialized doctor total is not 23")
        if len(policy_ids) != EXPECTED_POLICY_TOTAL:
            raise ManifestError("Materialized policy total is not 111")
        if not all(self._system_policy_inheritance.values()):
            raise ManifestError("Every component must inherit the System Core policy")
        self.inventory.assert_complete()
        return self.coverage_report()

    def coverage_report(self) -> CoverageReport:
        covered = sum(
            1
            for component in self._component_names
            if self._system_policy_inheritance.get(component)
        )
        policy_coverage = round((covered / len(self._component_names)) * 100)
        return CoverageReport(
            doctor_total=sum(len(lanes) for lanes in self.doctors.values()),
            policy_total=sum(len(slots) for slots in self.policies.values()),
            doctor_components=len(self.doctors),
            policy_components=len(self.policies),
            system_policy_coverage_percent=policy_coverage,
            inventory_coverage_percent=self.inventory.coverage_percent,
            cpu_logical_cores=self.cpu_policy.logical_cores,
            active_lane_limit=self.cpu_policy.max_parallel_doctors,
        )

    def mark_doctor_failed(self, doctor_id: str) -> None:
        doctor = self._doctor_by_id(doctor_id)
        doctor.failures += 1
        doctor.healthy = False

    def restore_doctor(self, doctor_id: str) -> None:
        self._doctor_by_id(doctor_id).healthy = True

    def _doctor_by_id(self, doctor_id: str) -> DoctorLane:
        for lanes in self.doctors.values():
            for doctor in lanes:
                if doctor.doctor_id == doctor_id:
                    return doctor
        raise DoctorUnavailableError(f"Unknown doctor: {doctor_id}")

    def _next_healthy_doctor(self, component: str) -> DoctorLane:
        lanes = self.doctors.get(component)
        if not lanes:
            raise DoctorUnavailableError(f"No doctors are registered for component: {component}")
        start = self._round_robin[component] % len(lanes)
        for offset in range(len(lanes)):
            index = (start + offset) % len(lanes)
            doctor = lanes[index]
            if doctor.healthy:
                self._round_robin[component] = index + 1
                return doctor
        raise DoctorUnavailableError(f"All doctors are unavailable for component: {component}")

    @contextmanager
    def acquire_doctor(
        self,
        component: str,
        *,
        wait: bool = False,
    ) -> Iterator[DoctorLane]:
        """Reserve one healthy doctor while enforcing a single active CPU lane."""

        acquired = self._execution_lock.acquire(blocking=wait)
        if not acquired:
            raise CoreBusyError("The single Amosclaud System Core lane is already active")
        try:
            yield self._next_healthy_doctor(component)
        finally:
            self._execution_lock.release()

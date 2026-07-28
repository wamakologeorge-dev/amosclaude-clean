from __future__ import annotations

import pytest

from amoscloud_ai.system_core import (
    AmosclaudSystemCore,
    CoreBusyError,
    DOCTOR_COUNTS,
    EXPECTED_DOCTOR_TOTAL,
    EXPECTED_POLICY_TOTAL,
    InventoryManifest,
    ManifestError,
    POLICY_COUNTS,
)


def test_system_core_materializes_exact_doctor_topology() -> None:
    core = AmosclaudSystemCore()

    assert {name: len(lanes) for name, lanes in core.doctors.items()} == DOCTOR_COUNTS
    assert sum(len(lanes) for lanes in core.doctors.values()) == EXPECTED_DOCTOR_TOTAL


def test_system_core_materializes_exact_policy_topology() -> None:
    core = AmosclaudSystemCore()

    assert {name: len(slots) for name, slots in core.policies.items()} == POLICY_COUNTS
    assert sum(len(slots) for slots in core.policies.values()) == EXPECTED_POLICY_TOTAL


def test_every_component_inherits_system_policy_and_single_core_budget() -> None:
    report = AmosclaudSystemCore().validate()

    assert report.system_policy_coverage_percent == 100
    assert report.inventory_coverage_percent == 100
    assert report.cpu_logical_cores == 1
    assert report.active_lane_limit == 1


def test_inventory_fails_closed_until_requirements_files_and_tools_are_complete() -> None:
    inventory = InventoryManifest.expected(
        requirements={"fastapi", "pytest"},
        files={"pyproject.toml", "README.md"},
        tools={"doctor", "fixer"},
    )
    inventory.record(
        requirements={"fastapi"},
        files={"pyproject.toml", "README.md"},
        tools={"doctor"},
    )
    core = AmosclaudSystemCore(inventory=inventory)

    assert core.coverage_report().inventory_coverage_percent == 67
    with pytest.raises(ManifestError, match="inventory is incomplete"):
        core.validate()

    inventory.record(requirements={"pytest"}, tools={"fixer"})
    assert core.validate().inventory_coverage_percent == 100


def test_single_core_rejects_a_second_active_doctor_lane() -> None:
    core = AmosclaudSystemCore()

    with core.acquire_doctor("amosclaud-autonomous") as first:
        assert first.component == "amosclaud-autonomous"
        with pytest.raises(CoreBusyError, match="single Amosclaud System Core lane"):
            with core.acquire_doctor("amosclaud-security"):
                raise AssertionError("unreachable")


def test_failed_doctor_hands_work_to_healthy_sibling() -> None:
    core = AmosclaudSystemCore()

    with core.acquire_doctor("amosclaud-fixer") as first:
        first_id = first.doctor_id

    core.mark_doctor_failed(first_id)

    with core.acquire_doctor("amosclaud-fixer") as second:
        assert second.doctor_id != first_id
        assert second.doctor_id.endswith("02")


def test_manifest_rejects_missing_or_extra_doctors_and_policies() -> None:
    bad_doctors = dict(DOCTOR_COUNTS)
    bad_doctors["amosclaud-fixer"] = 3
    with pytest.raises(ManifestError, match="Doctor manifest must exactly match"):
        AmosclaudSystemCore(doctor_counts=bad_doctors)

    bad_policies = dict(POLICY_COUNTS)
    bad_policies["amosclaud-api-key"] = 49
    with pytest.raises(ManifestError, match="Policy manifest must exactly match"):
        AmosclaudSystemCore(policy_counts=bad_policies)

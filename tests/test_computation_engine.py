import hashlib

import pytest

from amoscloud_ai.agent.computation_engine import (
    CalculationKind,
    CalculationLimits,
    CalculationStatus,
    ComputationEngine,
)


def test_storage_conversion_uses_decimal_megabytes() -> None:
    result = ComputationEngine().storage_bits(1, unit="megabytes")

    assert result.status is CalculationStatus.VERIFIED
    assert result.value == 8_000_000
    assert result.unit == "bits"
    assert result.evidence is not None
    assert "bits = size" in result.evidence.formulation


def test_sha256_digest_is_reproducible() -> None:
    payload = b"amosclaud"
    result = ComputationEngine().digest(payload)

    assert result.value == hashlib.sha256(payload).hexdigest()
    assert result.kind is CalculationKind.HASH
    assert result.confidence == 1.0


def test_weak_or_unapproved_hash_is_blocked() -> None:
    result = ComputationEngine().digest(b"data", algorithm="md5")

    assert result.status is CalculationStatus.BLOCKED
    assert result.evidence is None
    assert "not allowed" in result.blockers[0]


def test_entropy_of_two_equal_symbols_is_one_bit() -> None:
    result = ComputationEngine().shannon_entropy({"zero": 1, "one": 1})

    assert result.status is CalculationStatus.VERIFIED
    assert result.value == pytest.approx(1.0)
    assert result.unit == "bits/symbol"


def test_modular_power_matches_python_bounded_implementation() -> None:
    result = ComputationEngine().modular_power(5, 117, 19)

    assert result.value == pow(5, 117, 19)
    assert result.evidence is not None
    assert result.evidence.algorithm == "modular exponentiation"


def test_matrix_requires_rectangular_input() -> None:
    result = ComputationEngine().matrix_shape([[1, 2], [3]])

    assert result.status is CalculationStatus.BLOCKED
    assert "rectangular" in result.blockers[0]


def test_input_limit_prevents_unbounded_agent_work() -> None:
    engine = ComputationEngine(CalculationLimits(max_input_bytes=3))
    result = engine.digest(b"four")

    assert result.status is CalculationStatus.BLOCKED
    assert "safety limit" in result.blockers[0]


def test_verified_result_cannot_exist_without_evidence() -> None:
    from amoscloud_ai.agent.computation_engine import CalculationResult

    with pytest.raises(ValueError, match="require evidence"):
        CalculationResult(
            kind=CalculationKind.STORAGE,
            status=CalculationStatus.VERIFIED,
            value=8,
            unit="bits",
            confidence=1.0,
            evidence=None,
        )

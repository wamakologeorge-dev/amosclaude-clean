"""Deterministic, bounded computation services for Amosclaud Autonomous.

The engine gives autonomous agents a safe way to perform common mathematical and
computer-science calculations without arbitrary code execution. Every calculation
returns structured inputs, outputs, formulation, confidence, and reproducible
evidence so the Operations Center can display only work that actually occurred.

This module is intentionally not a cryptographic implementation. It can explain and
verify public mathematical properties, hashes, checksums, entropy, storage units, and
modular arithmetic, but it must not invent keys, claim encryption occurred, or replace
reviewed security libraries.
"""

from __future__ import annotations

import hashlib
import math
import operator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from functools import reduce
from typing import Iterable, Mapping


class CalculationKind(StrEnum):
    STORAGE = "storage"
    HASH = "hash"
    CHECKSUM = "checksum"
    ENTROPY = "entropy"
    MODULAR_ARITHMETIC = "modular_arithmetic"
    MATRIX = "matrix"


class CalculationStatus(StrEnum):
    VERIFIED = "verified"
    BLOCKED = "blocked"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class CalculationLimits:
    max_input_bytes: int = 10_000_000
    max_integer_bits: int = 4096
    max_matrix_cells: int = 100_000
    allowed_hashes: frozenset[str] = frozenset({"sha256", "sha384", "sha512"})

    def __post_init__(self) -> None:
        if self.max_input_bytes <= 0:
            raise ValueError("max_input_bytes must be positive")
        if self.max_integer_bits <= 0:
            raise ValueError("max_integer_bits must be positive")
        if self.max_matrix_cells <= 0:
            raise ValueError("max_matrix_cells must be positive")


@dataclass(frozen=True, slots=True)
class CalculationEvidence:
    algorithm: str
    formulation: str
    input_summary: str
    output_summary: str
    observed_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


@dataclass(frozen=True, slots=True)
class CalculationResult:
    kind: CalculationKind
    status: CalculationStatus
    value: object | None
    unit: str | None
    confidence: float
    evidence: CalculationEvidence | None
    blockers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")
        if self.status is CalculationStatus.VERIFIED and self.evidence is None:
            raise ValueError("verified calculations require evidence")
        if self.status is not CalculationStatus.VERIFIED and not self.blockers:
            raise ValueError("blocked or failed calculations require a reason")


class ComputationEngine:
    """Bounded deterministic calculations suitable for autonomous workflows."""

    def __init__(self, limits: CalculationLimits | None = None) -> None:
        self.limits = limits or CalculationLimits()

    def storage_bits(self, size: int, *, unit: str = "bytes") -> CalculationResult:
        factors = {
            "bits": 1,
            "bytes": 8,
            "kilobytes": 8_000,
            "megabytes": 8_000_000,
            "gigabytes": 8_000_000_000,
            "kibibytes": 8_192,
            "mebibytes": 8_388_608,
            "gibibytes": 8_589_934_592,
        }
        normalized = unit.lower()
        if size < 0:
            return self._blocked(CalculationKind.STORAGE, "size cannot be negative")
        if normalized not in factors:
            return self._blocked(CalculationKind.STORAGE, f"unsupported storage unit: {unit}")
        value = size * factors[normalized]
        if value.bit_length() > self.limits.max_integer_bits:
            return self._blocked(CalculationKind.STORAGE, "result exceeds integer safety limit")
        return self._verified(
            CalculationKind.STORAGE,
            value,
            "bits",
            algorithm="unit conversion",
            formulation=f"bits = size × {factors[normalized]}",
            input_summary=f"size={size}, unit={normalized}",
            output_summary=f"{value} bits",
        )

    def digest(self, data: bytes, *, algorithm: str = "sha256") -> CalculationResult:
        normalized = algorithm.lower()
        if normalized not in self.limits.allowed_hashes:
            return self._blocked(CalculationKind.HASH, f"hash algorithm is not allowed: {algorithm}")
        if len(data) > self.limits.max_input_bytes:
            return self._blocked(CalculationKind.HASH, "input exceeds byte safety limit")
        digest = hashlib.new(normalized, data).hexdigest()
        return self._verified(
            CalculationKind.HASH,
            digest,
            "hex",
            algorithm=normalized,
            formulation=f"digest = {normalized}(input_bytes)",
            input_summary=f"{len(data)} bytes",
            output_summary=digest,
        )

    def checksum(self, values: Iterable[int], *, modulus: int = 256) -> CalculationResult:
        if modulus <= 1:
            return self._blocked(CalculationKind.CHECKSUM, "modulus must be greater than one")
        numbers = tuple(values)
        if len(numbers) > self.limits.max_input_bytes:
            return self._blocked(CalculationKind.CHECKSUM, "input exceeds item safety limit")
        if any(not 0 <= value <= 255 for value in numbers):
            return self._blocked(CalculationKind.CHECKSUM, "checksum values must be bytes from 0 to 255")
        value = sum(numbers) % modulus
        return self._verified(
            CalculationKind.CHECKSUM,
            value,
            None,
            algorithm="modular byte sum",
            formulation="checksum = Σ byteᵢ mod modulus",
            input_summary=f"{len(numbers)} byte values, modulus={modulus}",
            output_summary=str(value),
        )

    def shannon_entropy(self, counts: Mapping[object, int]) -> CalculationResult:
        if not counts:
            return self._blocked(CalculationKind.ENTROPY, "at least one symbol count is required")
        if any(count < 0 for count in counts.values()):
            return self._blocked(CalculationKind.ENTROPY, "symbol counts cannot be negative")
        total = sum(counts.values())
        if total <= 0:
            return self._blocked(CalculationKind.ENTROPY, "total symbol count must be positive")
        if total > self.limits.max_input_bytes:
            return self._blocked(CalculationKind.ENTROPY, "symbol count exceeds safety limit")
        entropy = -sum(
            (count / total) * math.log2(count / total)
            for count in counts.values()
            if count
        )
        return self._verified(
            CalculationKind.ENTROPY,
            entropy,
            "bits/symbol",
            algorithm="Shannon entropy",
            formulation="H(X) = -Σ p(x) log₂ p(x)",
            input_summary=f"{len(counts)} symbols, total={total}",
            output_summary=f"{entropy:.12g} bits/symbol",
        )

    def modular_power(self, base: int, exponent: int, modulus: int) -> CalculationResult:
        if exponent < 0:
            return self._blocked(CalculationKind.MODULAR_ARITHMETIC, "negative exponents are not supported")
        if modulus <= 1:
            return self._blocked(CalculationKind.MODULAR_ARITHMETIC, "modulus must be greater than one")
        if any(value.bit_length() > self.limits.max_integer_bits for value in (base, exponent, modulus)):
            return self._blocked(CalculationKind.MODULAR_ARITHMETIC, "integer exceeds safety limit")
        value = pow(base, exponent, modulus)
        return self._verified(
            CalculationKind.MODULAR_ARITHMETIC,
            value,
            None,
            algorithm="modular exponentiation",
            formulation="result = base^exponent mod modulus",
            input_summary=f"base={base}, exponent={exponent}, modulus={modulus}",
            output_summary=str(value),
        )

    def matrix_shape(self, matrix: Iterable[Iterable[object]]) -> CalculationResult:
        rows = tuple(tuple(row) for row in matrix)
        if not rows:
            return self._blocked(CalculationKind.MATRIX, "matrix must contain at least one row")
        width = len(rows[0])
        if width == 0 or any(len(row) != width for row in rows):
            return self._blocked(CalculationKind.MATRIX, "matrix rows must be non-empty and rectangular")
        cells = len(rows) * width
        if cells > self.limits.max_matrix_cells:
            return self._blocked(CalculationKind.MATRIX, "matrix exceeds cell safety limit")
        value = (len(rows), width)
        return self._verified(
            CalculationKind.MATRIX,
            value,
            "rows×columns",
            algorithm="matrix dimension validation",
            formulation="shape(A) = (number of rows, number of columns)",
            input_summary=f"{cells} cells",
            output_summary=f"{value[0]}×{value[1]}",
        )

    @staticmethod
    def multiply_dimensions(*dimensions: int) -> int:
        """Return a bounded-size product helper for planners and estimators."""
        if not dimensions or any(value < 0 for value in dimensions):
            raise ValueError("dimensions must contain non-negative integers")
        return reduce(operator.mul, dimensions, 1)

    @staticmethod
    def _blocked(kind: CalculationKind, reason: str) -> CalculationResult:
        return CalculationResult(
            kind=kind,
            status=CalculationStatus.BLOCKED,
            value=None,
            unit=None,
            confidence=1.0,
            evidence=None,
            blockers=(reason,),
        )

    @staticmethod
    def _verified(
        kind: CalculationKind,
        value: object,
        unit: str | None,
        *,
        algorithm: str,
        formulation: str,
        input_summary: str,
        output_summary: str,
    ) -> CalculationResult:
        return CalculationResult(
            kind=kind,
            status=CalculationStatus.VERIFIED,
            value=value,
            unit=unit,
            confidence=1.0,
            evidence=CalculationEvidence(
                algorithm=algorithm,
                formulation=formulation,
                input_summary=input_summary,
                output_summary=output_summary,
            ),
        )

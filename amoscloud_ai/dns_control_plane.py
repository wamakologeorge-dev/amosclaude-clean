"""Independent Amosclaud DNS control plane.

This module owns desired DNS-zone state independently of Vercel. It deliberately
separates zone intent, validation, and verification so the Amosclaud Action can
act as the final judge before a DNS operation is considered successful.
"""
from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

RecordType = Literal["A", "AAAA", "CNAME", "MX", "TXT", "NS", "CAA"]
_RECORD_TYPES: set[str] = {"A", "AAAA", "CNAME", "MX", "TXT", "NS", "CAA"}
_LABEL_RE = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?|@)$", re.I)


class DNSControlError(ValueError):
    """A requested DNS operation is invalid or unsafe."""


@dataclass(frozen=True)
class DNSRecord:
    name: str
    type: RecordType
    value: str
    ttl: int = 300
    priority: int | None = None

    def normalized(self) -> "DNSRecord":
        name = normalize_name(self.name)
        value = self.value.strip()
        if self.type not in _RECORD_TYPES:
            raise DNSControlError(f"Unsupported DNS record type: {self.type}")
        if not value:
            raise DNSControlError("DNS record value is required")
        if not 30 <= self.ttl <= 86400:
            raise DNSControlError("TTL must be between 30 and 86400 seconds")
        if self.type == "A":
            try:
                if ipaddress.ip_address(value).version != 4:
                    raise ValueError
            except ValueError as exc:
                raise DNSControlError("A record requires an IPv4 address") from exc
        if self.type == "AAAA":
            try:
                if ipaddress.ip_address(value).version != 6:
                    raise ValueError
            except ValueError as exc:
                raise DNSControlError("AAAA record requires an IPv6 address") from exc
        if self.type in {"CNAME", "NS"}:
            value = normalize_name(value)
        if self.type == "MX" and (self.priority is None or self.priority < 0 or self.priority > 65535):
            raise DNSControlError("MX records require a priority from 0 to 65535")
        if self.type == "CAA" and self.priority is not None:
            raise DNSControlError("CAA records do not use priority")
        return DNSRecord(name=name, type=self.type, value=value, ttl=self.ttl, priority=self.priority)


def normalize_name(name: str) -> str:
    value = str(name or "").strip().lower().rstrip(".")
    if not value:
        raise DNSControlError("DNS name is required")
    if value == "@":
        return value
    labels = value.split(".")
    if any(not _LABEL_RE.fullmatch(label) for label in labels):
        raise DNSControlError(f"Invalid DNS label: {name}")
    return ".".join(labels)


@dataclass
class DNSZone:
    domain: str
    records: list[DNSRecord] = field(default_factory=list)
    serial: int = 1
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        self.domain = normalize_name(self.domain)
        self.records = [record.normalized() for record in self.records]

    def upsert(self, record: DNSRecord) -> DNSRecord:
        record = record.normalized()
        if record.name != "@" and not record.name.endswith("." + self.domain):
            raise DNSControlError("Record name must belong to the managed zone")
        if record.name == self.domain:
            record = DNSRecord("@", record.type, record.value, record.ttl, record.priority)
        self.records = [
            existing for existing in self.records
            if not (existing.name == record.name and existing.type == record.type and existing.value == record.value)
        ]
        self.records.append(record)
        self._touch()
        return record

    def delete(self, name: str, record_type: RecordType, value: str | None = None) -> int:
        normalized = normalize_name(name)
        before = len(self.records)
        self.records = [
            record for record in self.records
            if not (
                record.name == normalized
                and record.type == record_type
                and (value is None or record.value == value)
            )
        ]
        removed = before - len(self.records)
        if removed:
            self._touch()
        return removed

    def _touch(self) -> None:
        self.serial += 1
        self.updated_at = datetime.now(timezone.utc)

    def snapshot(self) -> dict:
        return {
            "domain": self.domain,
            "serial": self.serial,
            "updated_at": self.updated_at.isoformat(),
            "records": [record.__dict__ for record in self.records],
        }


@dataclass(frozen=True)
class DNSJudgeResult:
    passed: bool
    score: int
    reasons: tuple[str, ...]
    checks: dict[str, bool]


class AmosclaudDNSJudge:
    """Deterministic final judge for desired DNS state.

    The judge is intentionally non-AI and independent from the mutation path.
    A DNS change cannot be reported healthy unless every required check passes.
    """

    def judge(self, zone: DNSZone, *, observed_records: list[DNSRecord] | None = None) -> DNSJudgeResult:
        observed = {self._key(record.normalized()) for record in (observed_records or zone.records)}
        desired = {self._key(record) for record in zone.records}
        checks = {
            "zone_valid": bool(zone.domain and zone.serial > 0),
            "records_valid": all(self._record_safe(record) for record in zone.records),
            "desired_state_observed": desired <= observed,
            "no_duplicate_records": len(observed) == len(observed_records or zone.records),
        }
        reasons = tuple(name for name, passed in checks.items() if not passed)
        score = round(sum(checks.values()) / len(checks) * 100)
        return DNSJudgeResult(not reasons, score, reasons, checks)

    @staticmethod
    def _key(record: DNSRecord) -> tuple:
        return (record.name, record.type, record.value, record.ttl, record.priority)

    @staticmethod
    def _record_safe(record: DNSRecord) -> bool:
        try:
            record.normalized()
            return True
        except DNSControlError:
            return False


__all__ = [
    "AmosclaudDNSJudge",
    "DNSControlError",
    "DNSRecord",
    "DNSZone",
    "DNSJudgeResult",
    "normalize_name",
]

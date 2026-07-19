"""Privacy-safe, tamper-evident service events for the folder model."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

GENESIS_HASH = "0" * 64
_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _canonical(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


class ModelServiceLog:
    """Append-only JSONL audit log intended for one model-server process."""

    def __init__(self, root: Path):
        self.directory = root / "logs" / "service"
        self.directory.mkdir(parents=True, exist_ok=True)
        with _LOCKS_GUARD:
            self._lock = _LOCKS.setdefault(str(self.directory.resolve()), threading.Lock())

    def fingerprint(self, text: str) -> str:
        key = os.getenv("AMOSCLAUD_MODEL_LOG_HASH_KEY", "").encode()
        digest = (
            hmac.new(key, text.encode(), hashlib.sha256) if key else hashlib.sha256(text.encode())
        )
        return digest.hexdigest()

    def append(self, event: str, **fields: Any) -> dict[str, Any]:
        """Record metadata. Callers must never pass prompt, response, or credentials."""
        forbidden = {"prompt", "messages", "response", "reply", "authorization", "token", "api_key"}
        if forbidden.intersection(fields):
            raise ValueError("Sensitive content cannot be written to the model service log")
        with self._lock:
            previous_hash, sequence = self._last_link()
            record = {
                "schema": "amosclaud.model-service-log.v1",
                "sequence": sequence + 1,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event": event,
                "previous_hash": previous_hash,
                **fields,
            }
            record["event_hash"] = hashlib.sha256(
                previous_hash.encode("ascii") + _canonical(record)
            ).hexdigest()
            path = self.directory / f"{datetime.now(timezone.utc):%Y-%m-%d}.jsonl"
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            self._apply_retention()
            return record

    def events(self, limit: int = 100, event: str | None = None) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 1000))
        records = [item for item in self._read_all() if event is None or item.get("event") == event]
        return records[-limit:]

    def summary(self) -> dict[str, Any]:
        records = self._read_all()
        completions = [item for item in records if item.get("event") == "inference.completed"]
        failures = [item for item in records if item.get("event") == "inference.failed"]
        latencies = [float(item["latency_ms"]) for item in completions if "latency_ms" in item]
        return {
            "events": len(records),
            "completed": len(completions),
            "failed": len(failures),
            "total_tokens": sum(int(item.get("total_tokens", 0)) for item in completions),
            "average_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else 0,
            "last_sequence": records[-1].get("sequence", 0) if records else 0,
        }

    def verify(self) -> dict[str, Any]:
        previous_hash = GENESIS_HASH
        expected_sequence = 1
        count = 0
        anchored = False
        for path in sorted(self.directory.glob("????-??-??.jsonl")):
            for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                try:
                    record = json.loads(line)
                    actual_hash = record.pop("event_hash")
                    if not anchored and int(record.get("sequence", 1)) > 1:
                        # Retention can remove complete old daily files. The first
                        # retained record carries the signed link to that history.
                        previous_hash = str(record.get("previous_hash", GENESIS_HASH))
                        expected_sequence = int(record["sequence"])
                    anchored = True
                    calculated = hashlib.sha256(
                        previous_hash.encode("ascii") + _canonical(record)
                    ).hexdigest()
                    valid = (
                        record.get("previous_hash") == previous_hash
                        and record.get("sequence") == expected_sequence
                        and hmac.compare_digest(actual_hash, calculated)
                    )
                except (json.JSONDecodeError, KeyError, TypeError):
                    valid = False
                if not valid:
                    return {"valid": False, "events": count, "file": path.name, "line": line_number}
                previous_hash = actual_hash
                expected_sequence += 1
                count += 1
        return {"valid": True, "events": count, "last_hash": previous_hash}

    def _read_all(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for path in sorted(self.directory.glob("????-??-??.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return records

    def _last_link(self) -> tuple[str, int]:
        records = self._read_all()
        if not records:
            return GENESIS_HASH, 0
        last = records[-1]
        return str(last.get("event_hash", GENESIS_HASH)), int(last.get("sequence", 0))

    def _apply_retention(self) -> None:
        try:
            days = max(1, int(os.getenv("AMOSCLAUD_MODEL_LOG_RETENTION_DAYS", "30")))
        except ValueError:
            days = 30
        cutoff = datetime.now(timezone.utc).date() - timedelta(days=days)
        for path in self.directory.glob("????-??-??.jsonl"):
            try:
                if datetime.strptime(path.stem, "%Y-%m-%d").date() < cutoff:
                    path.unlink()
            except ValueError:
                continue

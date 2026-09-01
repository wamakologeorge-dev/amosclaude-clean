"""Tenant-scoped service contract for Amosclaud Postortores.

The service layer is the stable Amosclaud-facing contract. Storage engines may
change underneath it without changing how agents, SpaceCodeMe, runners, model
services, or the control plane address data.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .engine import PostortoresEngine
from .types import DataRecord, EvidenceRecord, EventRecord, MemoryRecord


class PostortoresService:
    """Scope native Postortores primitives to one Amosclaud principal."""

    def __init__(self, engine: PostortoresEngine, principal: str) -> None:
        principal = principal.strip()
        if not principal or ":" in principal:
            raise ValueError("principal must be a non-empty Amosclaud identifier without ':'")
        self.engine = engine
        self.principal = principal

    def _scope(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Postortores identifiers cannot be empty")
        return f"principal:{self.principal}:{value}"

    def put_state(
        self,
        namespace: str,
        key: str,
        value: dict[str, Any],
        tags: list[str] | None = None,
    ) -> DataRecord:
        return self.engine.put(
            DataRecord(
                namespace=self._scope(namespace),
                key=key,
                value=value,
                tags=list(tags or []),
            )
        )

    def get_state(self, namespace: str, key: str, version: int | None = None) -> DataRecord | None:
        return self.engine.get(self._scope(namespace), key, version)

    def state_history(self, namespace: str, key: str, *, offset: int = 0, limit: int = 100) -> list[DataRecord]:
        return self.engine.history(self._scope(namespace), key, offset=offset, limit=limit)

    def append_event(
        self,
        stream: str,
        event_type: str,
        payload: dict[str, Any],
        actor: str | None = None,
    ) -> int:
        return self.engine.append_event(
            EventRecord(
                stream=self._scope(stream),
                event_type=event_type,
                payload=payload,
                actor=actor or self.principal,
            )
        )

    def events(self, stream: str, after_id: int = 0, limit: int = 100) -> list[dict[str, Any]]:
        return self.engine.read_events(self._scope(stream), after_id=after_id, limit=limit)

    def remember(
        self,
        content: str,
        metadata: dict[str, Any] | None = None,
        embedding: list[float] | None = None,
    ) -> int:
        return self.engine.remember(
            MemoryRecord(
                owner=self._scope("memory"),
                content=content,
                metadata=metadata or {},
                embedding=embedding,
            )
        )

    def search_memory(self, embedding: list[float], limit: int = 10) -> list[dict[str, Any]]:
        return self.engine.search_memory(self._scope("memory"), embedding, limit=limit)

    def record_evidence(
        self,
        subject: str,
        claim: str,
        status: str,
        proof: dict[str, Any] | None = None,
    ) -> int:
        return self.engine.record_evidence(
            EvidenceRecord(
                subject=self._scope(subject),
                claim=claim,
                status=status,
                proof=proof or {},
            )
        )

    def evidence(self, subject: str) -> list[dict[str, Any]]:
        return self.engine.evidence_for(self._scope(subject))

    def link(
        self,
        source: str,
        relation: str,
        target: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.engine.link(
            self._scope(source),
            relation,
            self._scope(target),
            metadata=metadata,
        )

    def neighbors(self, source: str, relation: str | None = None) -> list[dict[str, Any]]:
        rows = self.engine.neighbors(self._scope(source), relation)
        prefix = f"principal:{self.principal}:"
        for row in rows:
            target = str(row["target"])
            if target.startswith(prefix):
                row["target"] = target[len(prefix) :]
        return rows

    def acquire_lease(self, resource: str, holder: str, ttl_seconds: float = 30.0) -> bool:
        return self.engine.acquire_lease(
            self._scope(resource),
            self._scope(f"holder:{holder}"),
            ttl_seconds=ttl_seconds,
        )

    def describe(self) -> dict[str, Any]:
        health = self.engine.health()
        return {
            "service": "Amosclaud Postortores",
            "principal": self.principal,
            "status": health["status"],
            "native_contract": True,
            "capabilities": [
                "versioned-state",
                "append-only-events",
                "semantic-agent-memory",
                "verification-evidence",
                "entity-graph",
                "worker-leases",
                "content-integrity-hashes",
            ],
        }

    def _unscope(self, value: str) -> str:
        prefix = f"principal:{self.principal}:"
        return value[len(prefix):] if value.startswith(prefix) else value

    def record_dict(self, record: DataRecord) -> dict[str, Any]:
        d = asdict(record)
        d["namespace"] = self._unscope(d["namespace"])
        return d

"""Signed, encrypted peer envelopes and deterministic CRDT state merging."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from .crypto_identity import (
    IdentityError,
    LocalNodeIdentity,
    PublicNodeIdentity,
    SealedMessage,
    _unb64,
    node_id_for_keys,
    verify_signature,
)


class PeerProtocolError(RuntimeError):
    """Raised when peer data fails validation or trust checks."""


@dataclass(frozen=True)
class RegisterValue:
    value: Any
    logical_clock: int
    node_id: str
    deleted: bool = False

    def rank(self) -> tuple[int, str, str]:
        digest = hashlib.sha256(
            json.dumps(
                self.value,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        ).hexdigest()
        return self.logical_clock, self.node_id, digest


class LWWMap:
    """Last-writer-wins map using Lamport clocks and deterministic tie breaking."""

    def __init__(self, records: Mapping[str, RegisterValue] | None = None) -> None:
        self._records = dict(records or {})

    def set(self, key: str, value: Any, *, logical_clock: int, node_id: str) -> None:
        self._put(
            key,
            RegisterValue(
                value=value,
                logical_clock=logical_clock,
                node_id=node_id,
                deleted=False,
            ),
        )

    def delete(self, key: str, *, logical_clock: int, node_id: str) -> None:
        self._put(
            key,
            RegisterValue(
                value=None,
                logical_clock=logical_clock,
                node_id=node_id,
                deleted=True,
            ),
        )

    def _put(self, key: str, candidate: RegisterValue) -> None:
        cleaned = str(key or "")
        if not cleaned or len(cleaned) > 1024:
            raise PeerProtocolError("CRDT key is invalid")
        if candidate.logical_clock < 0:
            raise PeerProtocolError("CRDT logical clock cannot be negative")
        current = self._records.get(cleaned)
        if current is None or candidate.rank() > current.rank():
            self._records[cleaned] = candidate

    def merge(self, other: "LWWMap") -> "LWWMap":
        result = LWWMap(self._records)
        for key, value in other._records.items():
            result._put(key, value)
        return result

    def materialize(self) -> dict[str, Any]:
        return {
            key: record.value
            for key, record in sorted(self._records.items())
            if not record.deleted
        }

    def snapshot(self) -> dict[str, dict[str, Any]]:
        return {
            key: asdict(value)
            for key, value in sorted(self._records.items())
        }

    @classmethod
    def from_snapshot(cls, payload: Mapping[str, Any]) -> "LWWMap":
        records: dict[str, RegisterValue] = {}
        for key, raw in payload.items():
            if not isinstance(raw, Mapping):
                raise PeerProtocolError("CRDT snapshot contains an invalid record")
            records[str(key)] = RegisterValue(
                value=raw.get("value"),
                logical_clock=int(raw["logical_clock"]),
                node_id=str(raw["node_id"]),
                deleted=bool(raw.get("deleted", False)),
            )
        return cls(records)


@dataclass(frozen=True)
class PeerEnvelope:
    protocol: str
    sender: PublicNodeIdentity
    sequence: int
    workspace_id: str
    payload_type: str
    encrypted_payload: SealedMessage
    signature: str

    def unsigned_dict(self) -> dict[str, Any]:
        return {
            "protocol": self.protocol,
            "sender": asdict(self.sender),
            "sequence": self.sequence,
            "workspace_id": self.workspace_id,
            "payload_type": self.payload_type,
            "encrypted_payload": self.encrypted_payload.to_dict(),
        }

    def canonical_bytes(self) -> bytes:
        return json.dumps(
            self.unsigned_dict(),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    def to_dict(self) -> dict[str, Any]:
        return {**self.unsigned_dict(), "signature": self.signature}

    @classmethod
    def create(
        cls,
        *,
        identity: LocalNodeIdentity,
        recipient: PublicNodeIdentity,
        sequence: int,
        workspace_id: str,
        payload_type: str,
        payload: Mapping[str, Any],
    ) -> "PeerEnvelope":
        if sequence < 1:
            raise PeerProtocolError("Peer sequence must be positive")
        if not workspace_id.startswith("ws_"):
            raise PeerProtocolError("Workspace ID is invalid")
        if not payload_type or len(payload_type) > 120:
            raise PeerProtocolError("Payload type is invalid")
        sender = identity.public_identity()
        aad = cls._aad(
            sender.node_id,
            recipient.node_id,
            sequence,
            workspace_id,
            payload_type,
        )
        plaintext = json.dumps(
            dict(payload),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        sealed = identity.seal_for(
            recipient.exchange_public_key,
            plaintext,
            associated_data=aad,
        )
        draft = cls(
            protocol="amosclaud-p2p-v1",
            sender=sender,
            sequence=sequence,
            workspace_id=workspace_id,
            payload_type=payload_type,
            encrypted_payload=sealed,
            signature="",
        )
        return cls(
            **{
                **draft.__dict__,
                "signature": identity.sign(draft.canonical_bytes()),
            }
        )

    @staticmethod
    def _aad(
        sender_id: str,
        recipient_id: str,
        sequence: int,
        workspace_id: str,
        payload_type: str,
    ) -> bytes:
        return (
            f"amosclaud-p2p-v1\0{sender_id}\0{recipient_id}\0"
            f"{sequence}\0{workspace_id}\0{payload_type}"
        ).encode("utf-8")

    def verify(
        self,
        *,
        trusted_sender_ids: set[str] | frozenset[str],
    ) -> None:
        if self.protocol != "amosclaud-p2p-v1":
            raise PeerProtocolError("Unsupported peer protocol")
        try:
            signing = _unb64(self.sender.signing_public_key)
            exchange = _unb64(self.sender.exchange_public_key)
        except IdentityError as exc:
            raise PeerProtocolError(str(exc)) from exc
        derived = node_id_for_keys(signing, exchange)
        if derived != self.sender.node_id:
            raise PeerProtocolError("Sender identity does not match its public keys")
        if self.sender.node_id not in trusted_sender_ids:
            raise PeerProtocolError("Sender is not trusted by this local node")
        try:
            verify_signature(
                self.sender.signing_public_key,
                self.canonical_bytes(),
                self.signature,
            )
        except IdentityError as exc:
            raise PeerProtocolError(str(exc)) from exc

    def decrypt(
        self,
        *,
        recipient_identity: LocalNodeIdentity,
        trusted_sender_ids: set[str] | frozenset[str],
    ) -> dict[str, Any]:
        self.verify(trusted_sender_ids=trusted_sender_ids)
        recipient = recipient_identity.public_identity()
        aad = self._aad(
            self.sender.node_id,
            recipient.node_id,
            self.sequence,
            self.workspace_id,
            self.payload_type,
        )
        try:
            plaintext = recipient_identity.open_sealed(
                self.encrypted_payload,
                associated_data=aad,
            )
            payload = json.loads(plaintext.decode("utf-8"))
        except (IdentityError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PeerProtocolError("Peer payload could not be decrypted") from exc
        if not isinstance(payload, dict):
            raise PeerProtocolError("Peer payload must be an object")
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "PeerEnvelope":
        try:
            sender_raw = payload["sender"]
            if not isinstance(sender_raw, Mapping):
                raise TypeError
            sender = PublicNodeIdentity(
                node_id=str(sender_raw["node_id"]),
                signing_public_key=str(sender_raw["signing_public_key"]),
                exchange_public_key=str(sender_raw["exchange_public_key"]),
            )
            encrypted_raw = payload["encrypted_payload"]
            if not isinstance(encrypted_raw, Mapping):
                raise TypeError
            return cls(
                protocol=str(payload["protocol"]),
                sender=sender,
                sequence=int(payload["sequence"]),
                workspace_id=str(payload["workspace_id"]),
                payload_type=str(payload["payload_type"]),
                encrypted_payload=SealedMessage.from_dict(encrypted_raw),
                signature=str(payload["signature"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise PeerProtocolError("Peer envelope is malformed") from exc

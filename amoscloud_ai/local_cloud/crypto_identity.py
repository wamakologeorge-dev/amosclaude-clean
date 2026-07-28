"""Cryptographic node identity and client-side encryption for local Amosclaud peers."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


class IdentityError(RuntimeError):
    """Raised when a node identity or encrypted message is invalid."""


@dataclass(frozen=True)
class PublicNodeIdentity:
    node_id: str
    signing_public_key: str
    exchange_public_key: str

    def canonical_bytes(self) -> bytes:
        return json.dumps(
            asdict(self),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")


@dataclass(frozen=True)
class SealedMessage:
    ephemeral_public_key: str
    nonce: str
    ciphertext: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "SealedMessage":
        try:
            return cls(
                ephemeral_public_key=str(payload["ephemeral_public_key"]),
                nonce=str(payload["nonce"]),
                ciphertext=str(payload["ciphertext"]),
            )
        except KeyError as exc:
            raise IdentityError("Encrypted payload is incomplete") from exc


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    text = str(value or "")
    try:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (ValueError, TypeError) as exc:
        raise IdentityError("Invalid base64 data") from exc


def _raw_public(key: Ed25519PublicKey | X25519PublicKey) -> bytes:
    return key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )


def _raw_private(key: Ed25519PrivateKey | X25519PrivateKey) -> bytes:
    return key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )


def node_id_for_keys(signing_public_key: bytes, exchange_public_key: bytes) -> str:
    digest = hashlib.sha256(
        b"amosclaud-node-v1\0" + signing_public_key + exchange_public_key
    ).hexdigest()
    return f"node_{digest[:40]}"


def signing_key_id(signing_public_key: bytes) -> str:
    return f"publisher_{hashlib.sha256(signing_public_key).hexdigest()[:40]}"


def verify_signature(public_key_b64: str, message: bytes, signature_b64: str) -> None:
    try:
        key = Ed25519PublicKey.from_public_bytes(_unb64(public_key_b64))
        key.verify(_unb64(signature_b64), message)
    except Exception as exc:
        raise IdentityError("Signature verification failed") from exc


class LocalNodeIdentity:
    """Persist signing and exchange keys only on the local node."""

    def __init__(self, identity_dir: Path) -> None:
        self.identity_dir = Path(identity_dir).expanduser().resolve()
        self.signing_file = self.identity_dir / "signing.key"
        self.exchange_file = self.identity_dir / "exchange.key"

    def _write_secret(self, path: Path, data: bytes) -> None:
        self.identity_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            os.chmod(self.identity_dir, 0o700)
        except OSError:
            pass
        with tempfile.NamedTemporaryFile(
            "wb",
            dir=self.identity_dir,
            delete=False,
            prefix=path.name + "-",
            suffix=".tmp",
        ) as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
            temporary = Path(handle.name)
        try:
            os.chmod(temporary, 0o600)
        except OSError:
            pass
        temporary.replace(path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

    def initialize(self) -> PublicNodeIdentity:
        if not self.signing_file.exists():
            self._write_secret(
                self.signing_file,
                _raw_private(Ed25519PrivateKey.generate()),
            )
        if not self.exchange_file.exists():
            self._write_secret(
                self.exchange_file,
                _raw_private(X25519PrivateKey.generate()),
            )
        return self.public_identity()

    def _signing_private(self) -> Ed25519PrivateKey:
        try:
            data = self.signing_file.read_bytes()
            return Ed25519PrivateKey.from_private_bytes(data)
        except (OSError, ValueError) as exc:
            raise IdentityError("Local signing identity is unavailable") from exc

    def _exchange_private(self) -> X25519PrivateKey:
        try:
            data = self.exchange_file.read_bytes()
            return X25519PrivateKey.from_private_bytes(data)
        except (OSError, ValueError) as exc:
            raise IdentityError("Local exchange identity is unavailable") from exc

    def public_identity(self) -> PublicNodeIdentity:
        signing = _raw_public(self._signing_private().public_key())
        exchange = _raw_public(self._exchange_private().public_key())
        return PublicNodeIdentity(
            node_id=node_id_for_keys(signing, exchange),
            signing_public_key=_b64(signing),
            exchange_public_key=_b64(exchange),
        )

    def publisher_id(self) -> str:
        signing = _raw_public(self._signing_private().public_key())
        return signing_key_id(signing)

    def sign(self, message: bytes) -> str:
        return _b64(self._signing_private().sign(message))

    def seal_for(
        self,
        peer_exchange_public_key: str,
        plaintext: bytes,
        *,
        associated_data: bytes = b"",
    ) -> SealedMessage:
        try:
            peer = X25519PublicKey.from_public_bytes(_unb64(peer_exchange_public_key))
        except (ValueError, TypeError) as exc:
            raise IdentityError("Peer exchange key is invalid") from exc
        ephemeral = X25519PrivateKey.generate()
        nonce = os.urandom(12)
        shared = ephemeral.exchange(peer)
        key = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=nonce,
            info=b"amosclaud-p2p-sealed-v1",
        ).derive(shared)
        ciphertext = ChaCha20Poly1305(key).encrypt(
            nonce,
            bytes(plaintext),
            associated_data,
        )
        return SealedMessage(
            ephemeral_public_key=_b64(_raw_public(ephemeral.public_key())),
            nonce=_b64(nonce),
            ciphertext=_b64(ciphertext),
        )

    def open_sealed(
        self,
        message: SealedMessage,
        *,
        associated_data: bytes = b"",
    ) -> bytes:
        try:
            ephemeral = X25519PublicKey.from_public_bytes(
                _unb64(message.ephemeral_public_key)
            )
            nonce = _unb64(message.nonce)
            ciphertext = _unb64(message.ciphertext)
            shared = self._exchange_private().exchange(ephemeral)
            key = HKDF(
                algorithm=hashes.SHA256(),
                length=32,
                salt=nonce,
                info=b"amosclaud-p2p-sealed-v1",
            ).derive(shared)
            return ChaCha20Poly1305(key).decrypt(
                nonce,
                ciphertext,
                associated_data,
            )
        except Exception as exc:
            raise IdentityError("Encrypted payload could not be opened") from exc

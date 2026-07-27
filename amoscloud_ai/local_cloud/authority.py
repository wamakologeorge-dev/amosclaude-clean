"""Independent local token authority with no external identity dependency."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import tempfile
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_PBKDF2_ITERATIONS = 240_000


class AuthorityError(RuntimeError):
    """Raised when the local authority cannot safely complete an operation."""


@dataclass(frozen=True)
class AuthorityState:
    instance_id: str
    created_at: str
    token_version: int


class LocalAuthority:
    """Own and verify a bearer token entirely on the local installation."""

    def __init__(self, state_dir: Path) -> None:
        self.state_dir = Path(state_dir).expanduser().resolve()
        self.state_file = self.state_dir / "authority.json"
        self._lock = threading.RLock()

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _hash_token(token: str, salt: bytes) -> str:
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            token.encode("utf-8"),
            salt,
            _PBKDF2_ITERATIONS,
        )
        return digest.hex()

    def _read(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.state_file.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise AuthorityError("Local authority is not initialized") from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise AuthorityError("Local authority state is unreadable") from exc
        required = {"instance_id", "created_at", "token_version", "salt", "token_hash"}
        if not required.issubset(payload):
            raise AuthorityError("Local authority state is incomplete")
        return payload

    def _write(self, payload: dict[str, Any]) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.state_dir, 0o700)
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=self.state_dir,
            delete=False,
            prefix="authority-",
            suffix=".tmp",
        ) as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
            temp_path = Path(handle.name)
        os.chmod(temp_path, 0o600)
        temp_path.replace(self.state_file)
        os.chmod(self.state_file, 0o600)

    def initialized(self) -> bool:
        return self.state_file.is_file()

    def initialize(self) -> tuple[AuthorityState, str | None]:
        """Initialize once and return the one-time plaintext token when newly created."""

        with self._lock:
            if self.initialized():
                return self.state(), None
            token = secrets.token_urlsafe(48)
            salt = secrets.token_bytes(32)
            payload = {
                "instance_id": f"local_{uuid.uuid4().hex}",
                "created_at": self._utc_now(),
                "token_version": 1,
                "salt": salt.hex(),
                "token_hash": self._hash_token(token, salt),
            }
            self._write(payload)
            return self.state(), token

    def state(self) -> AuthorityState:
        payload = self._read()
        return AuthorityState(
            instance_id=str(payload["instance_id"]),
            created_at=str(payload["created_at"]),
            token_version=int(payload["token_version"]),
        )

    def verify(self, supplied_token: str) -> bool:
        if not supplied_token:
            return False
        with self._lock:
            payload = self._read()
            salt = bytes.fromhex(str(payload["salt"]))
            expected = str(payload["token_hash"])
            actual = self._hash_token(supplied_token, salt)
            return hmac.compare_digest(actual, expected)

    def rotate(self) -> str:
        """Invalidate the old token and return a new one exactly once."""

        with self._lock:
            payload = self._read()
            token = secrets.token_urlsafe(48)
            salt = secrets.token_bytes(32)
            payload.update(
                {
                    "token_version": int(payload["token_version"]) + 1,
                    "rotated_at": self._utc_now(),
                    "salt": salt.hex(),
                    "token_hash": self._hash_token(token, salt),
                }
            )
            self._write(payload)
            return token
